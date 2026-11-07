#!/usr/bin/env python3
"""
host_resolvers.py — stdlib-only, read-only resolvers for third-party hosts.

No database access, no writes anywhere but a socket read: an importer asks a
question about one URL and gets a verdict back. Pure Python standard library,
zero pip packages, importable from any importer in this directory.

WHY THIS MODULE EXISTS
----------------------
`AGENTS.md` and the owner's rule for this project are the same: an iframe is
catalog metadata, never a playable row, because the Android client has no
WebView escape hatch. A host is therefore only interesting here if a plain
HTTP request chain — no browser, no JS engine — gets from its page to a byte
endpoint. That is exactly what mxdrop does, verified live on 2026-10-28 against
six different posts (Land of the Lost, Bigg Boss Ep 51, The One About Matthew
Perry, Crawlers, Chand Mera Dil, plus three more sampled from the REST feed):

    GET https://mxdrop.to/e/<id>                     200, one packed script
    unpack the Dean-Edwards p/a/c/k/e/d payload      MDCore.* config
    https: + MDCore.wurl                             a direct .mp4
    Range: bytes=0-511, NO Referer                   206 video/mp4, \\x00\\x00\\x00 ftypisom

The unpacker mirrors the packer's own loop, including its odd detail: in this
build `e` is the identity function (`e=function(c){return c}`), so the
substitution really is "replace every standalone occurrence of the index,
written in base `a`, with the key list entry at that index". Indices are walked
highest-first, exactly like the packer's `while(c--)`, which also keeps an
inserted value (a 32-char hex file hash is full of digits) from ever being
re-substituted.

PKEMBED — THE SAME CHAIN, A DIFFERENT SCRIPT
--------------------------------------------
Verified live on 2026-10-28 against four posts (Bigg Boss Ep 51, haiwaan,
Crawlers, The One About Matthew Perry), and it is the dominant player on that
catalog: 100 of the newest 100 posts carry a `pkembed.site/embed-<id>.html`
iframe. The chain is the same shape and the same two requests:

    GET https://pkembed.site/embed-<id>.html          200, one packed script
    unpack it with radix 36                           a fluidPlayer() call
    <source src="https://plus22.vkpluscdn.site/v/01/00002/<id>_l/l.mp4
              ?t=<sig>&s=<issue epoch>&e=43200&v=<view id>&sp=3000&i=0.3">
    Range: bytes=0-511, NO Referer                    206 video/mp4

Three details differ from mxdrop, and each is encoded rather than assumed:

* The packer is called with four arguments, not mxdrop's six (no trailing
  `0,{}`), and its radix is 36, so the indices are words like `1f` (=51) and
  `4g` (=160). `PACKER_RE` accepts both tails; `to_base` supplies the radix.
* The payload is a JS single-quoted literal, so it arrives holding `\\'`
  escapes that the parser removes before the packer runs.
  `_unescape_js_string` does that first; substituting first would corrupt them.
* `e` is not an expiry timestamp here. `s` is the issue epoch (measured equal
  to the clock at unpack time, `s - now = 0`) and `e=43200` is a twelve-hour
  *lifetime*, so the answer is `s + e - now` — `duration_expiry_from_url`, kept
  separate from mxdrop's `expiry_from_url` because each one rejects the other's
  query by digit count. `expiry_from_url` would read `e=43200` as an epoch in
  1970 and call a working file expired.

A page may offer one rendition or two (`_l` and `_n`, titled e.g. "360p 414
kbps" and "480p 658 kbps"); `final_url` is the highest of them and `sources`
lists every one, so the catalog keeps the quality labels the host published.

THE REFERER RULE IS NOT COSMETIC
--------------------------------
Measured on the same six posts: the MP4 answers `206` with no Referer and with
`Referer: https://mxdrop.top/e/<id>`, and `403` with
`Referer: https://www.moviesmela.com/`. So this module never attaches a
referrer to a media request — see FORBIDDEN_REFERRERS — and an importer that
already knows the catalog page's URL must still not pass it here. A resolver
that "helpfully" sends the source site as Referer turns a working catalog into
a wall of 403s, and every probe below is written so that the mistake cannot be
made by accident.

SHORT-LIVED URLS: WHAT MAY BE STORED
------------------------------------
`MDCore.wurl` is signed (`s`), carries an expiry (`e`, roughly six hours out)
and a ticket (`_t`); pkembed signs its renditions with `t` and stamps the issue
epoch in `s` with a twelve-hour lifetime in `e`. Replaying a stored signature
returns 403 while the host's own poster still returns 200, which is how
`unwrap_mxdrop` and `unwrap_pkembed` tell "this signature expired" from "this
host is gone". The consequence for callers is explicit: **the embed URL is the
durable identifier; the mp4 URL is a result of this call and must not be
persisted.** Both resolvers therefore return it to the caller and leave it out
of every stored shape.

GOOGLE DRIVE — A FILE HOST BEING USED AS A VIDEO HOST
-----------------------------------------------------
`animahd.com` publishes one Google Drive file id per episode (`data-fileid`), so
its "host" is a general file store with no embed page and no packer. One request
to the download endpoint has three possible answers, all measured live on
2026-10-28 (owner) against a real episode id:

    GET https://drive.google.com/uc?export=download&id=<id>   200 text/html
        the "Virus scan warning" interstitial a file over ~100 MB answers with,
        whose body carries <form action="https://drive.usercontent.google.com/
        download"> with hidden `id` / `export=download` / `confirm=t` / `uuid`;
    GET that form action + `Range: bytes=0-511`              206,
        `Content-Range bytes 0-511/253161185`, magic `1A45DFA3`,
        `Content-Type: application/octet-stream`;
    302 straight to the bytes, which is what a small public file does instead.

Two consequences are coded here rather than assumed. Drive labels *every* file
`application/octet-stream`, so the Range probe cannot recognise video from the
content type and reads the container header instead (`container_magic`). And a
refusal is a quota, not a verdict: Drive throttles downloads per file per day,
so 403/429/503 come back as `unverified` with one attempt spent and no retry —
hammering a rate limit is how one blocked file gets the whole client blocked.
Unlike the two packer hosts, the durable identifier here is the file id, so
`verify=False` asks Drive for nothing at all.

ANIMAHD — THE SAME FILE, TWO HOSTS, ONE DURABLE URL
---------------------------------------------------
The same `animahd.com` row that carries a Drive file id also carries the site's
own watch link, and that link turned out to be resolvable without a browser —
`AGENTS.md`'s "an iframe is never a playable row" rule does not apply to a page
whose script is one `window.location.replace` of a literal printed in its own HTML.
Verified live on 2026-10-28, one request per hop:

    GET https://animahd.com/player/?file_id=<id>&show_id=<post>&ep=<n>   200, 84 KB
        const targetStreamUrl = "https://<varies>.animahd.fun/?id=<id>";
        window.location.replace(targetStreamUrl);
    GET https://<varies>.animahd.fun/?id=<id>   200, 57 KB, with a browser UA and
        NO Referer (the same request with no UA at all answers 403)
        <video id="player"><source src="https://<sub>.animahdNNN.workers.dev/
        ?eid=…&token=…&v=0&ext=.mp4" type="video/mp4">
    GET that URL with Range: bytes=0-511   206, video/x-matroska,
        Content-Range bytes 0-511/253161185, magic 1A45DFA3, no Referer needed

Three measurements decide the shape of `unwrap_animahd`. The secure host's label
is not fixed — `theultimateanimehub` and `animeepisodesandmore` were both seen —
so it is read out of the player page each time and never stored. `token`
regenerates on every load of the secure page (`eid` stayed put), so the worker
URL is a result, never catalog data; a URL minted at 17:16 still answered 206 at
17:48, so `expires_in` claims a deliberately conservative 1800 s against a
measured window of at least 32 minutes whose ceiling nobody has observed. And the
page's `<source type="video/mp4">` is contradicted by its own bytes (EBML,
served as `video/x-matroska`), so the mime a caller receives is the response's,
not the declaration.

HOSTS DELIBERATELY NOT IMPLEMENTED — THE VERDICT, WITH THE MEASUREMENTS
-----------------------------------------------------------------------
Two other players in this catalog were examined on 2026-10-28 and each got the
same answer: **NEEDS-JS.** No code in this module pretends to resolve them; the
measurements are recorded here so the verdict is auditable rather than re-argued.

`movieshub.rpmplay.xyz` — a Vite single-page app, not a page.

    GET /                                        200, 1386 bytes: title
                                                 "Loading...", an empty <body>,
                                                 one <script type="module">
    GET /api/v1/player?t=test                   200 {"error": "Token is invalid"}
    GET /api/v1/video?id=test                   400 {"message": "Request is invalid"}
    GET /api/v1/log?t=test                      200 {"error": "Token is invalid"}
    GET /api/v1/info                             200 application/octet-stream,
                                                 3040 hex chars = 95 16-byte
                                                 blocks; two calls 12 s apart
                                                 differ from the first byte

There is no URL to extract: the host answers with an AES-CBC ciphertext that is
re-randomised per request, and the key is not in the bundle — `index-B82x0F06.js`
(974,778 bytes) contains no CryptoJS and no static key/IV or hex-decode helper
outside hls.js. What it does contain is `crypto.subtle.importKey("raw", …,
"AES-CBC")` beside a minified software-AES fallback, a `capacityToken`
handshake with server-driven `capacityTokenExpire`/`retryAfter` exponential
backoff, `crypto.randomUUID()`, and browser-integrity probes (`webdriver`,
`visibilityState`, `ancestorOrigins`, `adBlock`). Reaching a byte therefore needs
both a JS engine *and* an imitation of checks whose stated purpose is to keep
non-browser clients out — that is a headless browser plus anti-bot evasion, not
a resolver, and this project does not ship either.

`filemoon.to` — the same shape, one tier worse.

    GET /e/<anything>                            200, 1605 bytes: title "Byse
                                                 Frontend", <body><div
                                                 id="root"></div></body>, a
                                                 bootstrap that only adds a CSS
                                                 class; zero media URLs
    GET /assets/index-DocunfmE.js                TLS handshake refused by the
                                                 asset host (curl exit 35 over
                                                 HTTP/2 and HTTP/1.1 alike)
    GET https://filemoon.org/e/<unknown id>      302 -> /en, a 282 KB landing
                                                 page, not a file

So a plain request chain cannot even read the code that would tell it where the
file is. `filemoon` rows stay `playback_type='iframe'` / `status='unverified'`
in the catalog: honest evidence that the site published a player, and no claim
that a client can play it.
"""

from __future__ import annotations

import base64
import json
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)
DEFAULT_TIMEOUT = 25
RANGE_PROBE_BYTES = 512
# A probe reads a header-sized slice, never a whole file.
PROBE_READ_BYTES = 200_000

# Hosts whose page holds a packed MDCore config. `mxdrop.to` and `mxdrop.top`
# both serve it; membership is label-anchored so a look-alike host is not
# mistaken for this one. Unlike pkembed, mxdrop does NOT serve the bare
# `/<code>` form: `https://mxdrop.to/xo78jxvjagwq9x` answers 200 with a 10,692-byte
# page titled "MixDrop" and no packed config, so the path rule stays `/e/` and
# `/embed/` only.
MXDROP_HOST_RE = re.compile(r"(?:^|\.)mxdrop\.(?:to|top)$", re.I)
MXDROP_CONTENT_RE = re.compile(r"^/(?:e|embed)/[A-Za-z0-9_-]+/?$", re.I)

# pkembed serves the same page under two paths: `/embed-<filecode>.html` and the
# bare `<filecode>.html`. Both were verified live on 2026-10-28 — the bare form
# (`/zp8vd43rpa80.html`) answers 200 with the same packed config and the same
# two renditions, and it is the URL this catalog writes into a `download` row —
# so a matcher that requires the `embed-` prefix silently un-resolves real files.
# The shape is still NOT mxdrop's `/e/<id>`: a matcher that requires `/e/` finds
# zero pkembeds. `pkembed.online` is a sibling this catalog publishes rarely and
# has not been re-verified here, so it is recognized but stays honest: an
# unpack that fails on it reports `unknown`, never `active`.
PKEMBED_HOST_RE = re.compile(r"(?:^|\.)pkembed\.(?:site|online)$", re.I)
PKEMBED_CONTENT_RE = re.compile(r"^/(?:embed-)?[A-Za-z0-9]{6,}\.html$", re.I)

# eval(function(p,a,c,k,e,d){…}('<payload>',10,27,'k1|k2|…'.split('|'),0,{}))
# mxdrop's build ends with the trailing `0,{}` pair; pkembed's ends at
# `.split('|')`. The tail is therefore optional, never anchored.
PACKER_RE = re.compile(
    r"""eval\(\s*function\s*\(\s*p\s*,\s*a\s*,\s*c\s*,\s*k\s*,\s*e\s*,\s*d\s*\)"""
    r"""\s*\{.*?\}\s*\(\s*'(.*?)'\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*'(.*?)'"""
    r"""\s*\.split\(\s*'\|'\s*\)\s*(?:,\s*\d+\s*,\s*\{\}\s*)?\)\s*\)""",
    re.S,
)
# The payload is a JS single-quoted literal, so it reaches Python still holding
# `\'` and `\\`. The packer's substitutions run on the parsed value, not on the
# source text.
JS_STRING_ESCAPE_RE = re.compile(r"\\([\\'])")
MD_FIELD_RE = re.compile(r'MDCore\.(\w+)\s*=\s*"([^"]*)"')
MD_ARRAY_RE = re.compile(r"MDCore\.(\w+)\s*=\s*(\[(?:[^\[\]]|\[[^\[\]]*\])*\])")
SIGNED_QUERY_KEYS = frozenset({"s", "t", "sig", "signature", "token", "auth_key", "_t",
                               "e", "expires", "exp"})

# pkembed publishes the file as `<source>` tags inside a fluidPlayer() call.
PK_SOURCE_TAG_RE = re.compile(r"<source\b[^>]*>", re.I)
PK_ATTR_RE = re.compile(r"([\w-]+)\s*=\s*\"([^\"]*)\"")
PK_POSTER_RE = re.compile(r"""posterImage\s*:\s*['"]([^'"]+)['"]""")
# The media host is not fixed: `plus1`/`plus22.vkpluscdn.site` and
# `stoplus.vkcdn5.com` were all seen serving the same file code, so the host is
# whatever the payload says and is never pinned or guessed here.
MEDIA_URL_RE = re.compile(
    r"""(?:(?:https?:)?//)[^\s"'<>()\\]+?\.(?:mp4|m3u8|webm|mpd)(?:\?[^\s"'<>()\\]*)?""",
    re.I)
# Captions on this host are a view-ping (`…&upload_srt=`), not a published
# track, so a subtitle is recorded only when an actual .vtt/.srt URL is present.
PK_SUB_RE = re.compile(r"""['"]((?:https?:)?//[^'"]+?\.(?:vtt|srt)(?:\?[^'"]*)?)['"]""")

# Referrers that are known to make these hosts answer 403. Never sent, checked
# in code so a future caller cannot reintroduce the bug.
FORBIDDEN_REFERRERS = ("moviesmela", "hindidubbedmovies", "moviehax")

# Google Drive names a file two ways: the download endpoint's `?id=`, and the
# viewer's `/file/d/<id>/view`. Both are the same file, and the id is the only
# part worth keeping — the rest of either URL is a request shape, not identity.
GDRIVE_HOST_RE = re.compile(r"(?:^|\.)drive\.google\.com$", re.I)
GDRIVE_ID_RE = re.compile(r"[0-9A-Za-z_-]{20,}")
GDRIVE_DOWNLOAD_PAGE = "https://drive.google.com/uc"
# Only a form pointing at Google's own byte host gets replayed. A page's form
# action is the page's data, not an instruction for where to send the next
# request, so an interstitial that named somebody else's host is refused here.
GDRIVE_BYTE_HOSTS = ("drive.usercontent.google.com", "drive.google.com", "docs.google.com")
GDRIVE_FORM_RE = re.compile(
    r"""<form\b[^>]*\baction\s*=\s*["'](?P<action>[^"']*)["'][^>]*>(?P<body>.*?)</form>""",
    re.I | re.S)
GDRIVE_INPUT_RE = re.compile(r"<input\b[^>]*>", re.I)
GDRIVE_ATTR_RE = re.compile(r"""\b(?P<name>type|name|value)\s*=\s*["'](?P<value>[^"']*)["']""",
                            re.I)

SERVICE_MXDROP = "mxdrop"
SERVICE_PKEMBED = "pkembed"
SERVICE_GDRIVE = "gdrive"
SERVICE_ANIMAHD = "animahd-player"
SERVICE_VIDBOLT = "vidbolt"
SERVICE_VIBUXER = "vibuxer"
SERVICE_VIDRIFT = "vidrift"
SERVICE_IQSMART = "iqsmart"
SERVICE_FILMU = "filmu"
SERVICE_CINEVERSE = "cineverse"

VIDBOLT_HOST_RE = re.compile(r"(?:^|\.)vidbolt\.(?:xyz|pro)$", re.I)
VIDBOLT_CONTENT_RE = re.compile(
    r"^/(?:embed/)?(?:movie|tv)/([A-Za-z0-9_-]+)(?:/([A-Za-z0-9_-]+)/([A-Za-z0-9_-]+))?/?$",
    re.I)
VIBUXER_HOST_RE = re.compile(r"(?:^|\.)vibuxer\.com$", re.I)
VIBUXER_CONTENT_RE = re.compile(r"^/(?:e|embed)/([A-Za-z0-9_-]+)/?$", re.I)
VIDRIFT_HOST_RE = re.compile(r"(?:^|\.)vidrift\.net$", re.I)
VIDRIFT_CONTENT_RE = re.compile(
    r"^/(?:embed/)?(?:movie|tv)/([A-Za-z0-9_-]+)(?:/([A-Za-z0-9_-]+)/([A-Za-z0-9_-]+))?/?$",
    re.I)
IQSMART_HOST_RE = re.compile(r"(?:^|\.)iqsmartgames\.com$", re.I)
IQSMART_CONTENT_RE = re.compile(
    r"^/embed/(?:movie|tv)/([A-Za-z0-9_-]+)(?:/([0-9]+)/([0-9]+))?/?$",
    re.I)
FILMU_HOST_RE = re.compile(r"(?:^|\.)(?:filmu\.in|vidly\.pro)$", re.I)
FILMU_CONTENT_RE = re.compile(
    r"^/(?:embed/)?(?:movie|tv)/([A-Za-z0-9_-]+)(?:/([0-9]+)/([0-9]+))?/?$",
    re.I)
CINEVERSE_HOST_RE = re.compile(r"(?:^|\.)(?:modiplay\.xyz|cineverse\.[a-z]+)$", re.I)
CINEVERSE_CONTENT_RE = re.compile(
    r"^/embed/tmdb/(?:movie|tv)/?$",
    re.I)
VIDBOLT_DEFAULT_EXPIRY_SECONDS = 14400  # 4 hours conservative cache window

# AnimaHD's own player page. It is not an iframe and it is not a JS puzzle: the
# page's script is `const targetStreamUrl = "<literal>"; …
# window.location.replace(targetStreamUrl)`, so the destination is in the HTML
# and a server-side fetch can follow it. Measured on 2026-10-28 on two
# different files: the secure host NAME varies per file (`theultimateanimehub`
# and `animeepisodesandmore` were both served), so it is read out of the page
# every time and never stored or pinned — only the player URL is durable.
ANIMAHD_HOST_RE = re.compile(r"(?:^|\.)animahd\.com$", re.I)
ANIMAHD_PLAYER_PATH_RE = re.compile(r"^/player/?$", re.I)
ANIMAHD_TARGET_RE = re.compile(
    r"""["']https://((?:[A-Za-z0-9-]+\.)+)animahd\.fun/\?id=([A-Za-z0-9_-]{6,})["']""",
    re.I)
# The secure page's own media tag: <video id="player" …><source src="…workers.dev/
# ?eid=…&token=…&v=0&ext=.mp4">. One per page (measured), and its `src` is about
# 2,900 characters long, which is why the value is captured rather than counted.
ANIMAHD_SOURCE_RE = re.compile(
    r"""<source\b[^>]*?\bsrc\s*=\s*["']([^"']+)["']""", re.I | re.S)
# The byte host is Cloudflare Workers under `animahdNNN.workers.dev`, but the
# name is the deployer's choice, so the guard is structural: an https URL whose
# host ends in `workers.dev` and whose query carries `eid` and `token`.
ANIMAHD_WORKER_RE = re.compile(r"(?:^|\.)workers\.dev$", re.I)
# The page's own words for "Google's per-file quota is spent, so the file is not
# playing right now". The branch is client-side, so its presence alone does not
# make the `<source>` a lie — it just names why a probe may fail.
ANIMAHD_LOCKED_RE = re.compile(r"Stream Locked by Google|API limit has been reached", re.I)
# `token` regenerates on every load of the secure page (`eid` stayed put). A URL
# minted at 17:16 still answered 206 at 17:48, so the window is at least ~32
# minutes and nobody has measured its ceiling: 1800 is what this module claims,
# deliberately shorter than the shortest observation.
ANIMAHD_TOKEN_SECONDS = 1800
# Measured from the live host's own header on a 206 response, twice. The URL ends
# in `ext=.mp4` and the bytes are EBML, so the extension is the least trustworthy
# statement on the page and the mime here comes from the response, not the name.
ANIMAHD_MIME = "video/x-matroska"


# ---------------------------------------------------------------------------
# Fetch seams — one primitive, so tests can drive the real bodies offline
# ---------------------------------------------------------------------------

def _build_ssl_context() -> ssl.SSLContext:
    return ssl.create_default_context()


class _StopRedirect(urllib.request.HTTPRedirectHandler):
    """Keeps a redirect visible as a verdict instead of silently following it."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENERS = {}


def _build_openers(context: ssl.SSLContext | None = None):
    """
    (follow-opener, no-follow-opener), cached per context.

    The key is the context object itself, not `id()` of it: a recycled address
    would otherwise hand back openers built for a certificate store that no
    longer exists.
    """
    context = context or _build_ssl_context()
    cached = _OPENERS.get(context)
    if cached is not None:
        return cached
    https = urllib.request.HTTPSHandler(context=context)
    built = (urllib.request.build_opener(https),
             urllib.request.build_opener(https, _StopRedirect()))
    _OPENERS[context] = built
    return built


_SSL_CONTEXT = _build_ssl_context()
_FOLLOW, _NO_FOLLOW = _build_openers(_SSL_CONTEXT)


def _open(request: urllib.request.Request, timeout: float = DEFAULT_TIMEOUT,
          follow: bool = True):
    """The only socket call in this module; everything above it is testable."""
    opener = _FOLLOW if follow else _NO_FOLLOW
    return opener.open(request, timeout=timeout)


def http_request(url: str, headers: dict | None = None, timeout: float = DEFAULT_TIMEOUT,
                 method: str = "GET", follow: bool = True, data: bytes | None = None):
    """
    (status, body, headers, final_url) for one request.

    A redirect that was asked not to be followed comes back as its 3xx with the
    Location in `headers`; a transport failure comes back as status 0 with the
    reason in the body, because a resolver's job is to name what it saw.
    """
    fields = {"User-Agent": USER_AGENT}
    fields.update(headers or {})
    request = urllib.request.Request(url, headers=fields, method=method, data=data)
    try:
        with _open(request, timeout=timeout, follow=follow) as response:
            return (int(response.status), response.read(PROBE_READ_BYTES),
                    {k.lower(): v for k, v in response.getheaders()},
                    response.geturl())
    except urllib.error.HTTPError as exc:
        return (int(exc.code), exc.read(PROBE_READ_BYTES),
                {k.lower(): v for k, v in (exc.headers.items() if exc.headers else [])},
                url)
    except Exception as exc:                      # DNS, TLS, timeout, refused
        return 0, str(exc), {}, url


# ---------------------------------------------------------------------------
# The packer — pure, no I/O
# ---------------------------------------------------------------------------

def to_base(value: int, base: int) -> str:
    """The packer's `i.toString(a)`: index 62 in base 62 is "10"."""
    if base < 2 or base > len(BASE_ALPHABET):
        raise ValueError(f"unsupported radix {base}")
    if value == 0:
        return BASE_ALPHABET[0]
    out = ""
    while value:
        value, rem = divmod(value, base)
        out = BASE_ALPHABET[rem] + out
    return out


def unpack_packed_js(payload: str, radix: int, count: int, keys: list[str]) -> str:
    """
    The Dean Edwards unpacker, faithful to the emitted script.

    Walks the indices highest-first and substitutes only whole words, so digits
    that arrive inside a replaced value are never re-read as an index. An empty
    key (the packer's spare slots) is skipped, exactly like the packer's
    `if(k[c])` test — and that skip is load-bearing, not tidiness: pkembed's
    `k[0]` is the empty string, and replacing `0` with it would silently erase
    every literal zero in the payload.
    """
    out = payload
    for index in range(min(count, len(keys)) - 1, -1, -1):
        key = keys[index]
        if not key:
            continue
        token = re.escape(to_base(index, radix))
        out = re.sub(rf"\b{token}\b", lambda _m, value=key: value, out)
    return out


def find_packed_config(html: str) -> str:
    """The unpacked script text, or "" when the page holds no recognisable packer."""
    match = PACKER_RE.search(html or "")
    if not match:
        return ""
    payload, radix, count, keylist = match.group(1), int(match.group(2)), int(match.group(3)), \
        match.group(4).split("|")
    return unpack_packed_js(JS_STRING_ESCAPE_RE.sub(r"\1", payload), radix, count, keylist)


def parse_mdcore(config: str) -> dict:
    """
    MDCore assignments -> a dict, plus the subtitle map if the host published one.

    Only fields that are literally present are returned; an absent `sublangs`
    stays absent rather than becoming an invented track list.
    """
    out: dict[str, object] = {}
    for name, value in MD_FIELD_RE.findall(config or ""):
        out[name] = value
    for name, literal in MD_ARRAY_RE.findall(config or ""):
        parsed = _parse_pair_array(literal)
        if parsed is not None:
            out[name] = parsed
    return out


def _parse_pair_array(literal: str) -> list[tuple[str, str]] | None:
    """
    `[["English","//h/en.vtt"], …]` -> the pairs, or None when the value is not a
    list of pairs.

    A field this module cannot read stays unread rather than becoming an
    invented subtitle track.
    """
    try:
        loaded = json.loads(literal)
    except json.JSONDecodeError:
        pairs = re.findall(r'\[\s*"([^"]*)"\s*,\s*"([^"]*)"', literal or "")
        return pairs or None
    if isinstance(loaded, list) and all(
            isinstance(item, list) and len(item) == 2 for item in loaded):
        return [(str(first), str(second)) for first, second in loaded]
    return None


def absolutize(url: str) -> str:
    """Protocol-relative -> https. The host's own config is always relative."""
    text = (url or "").strip()
    if text.startswith("//"):
        return "https:" + text
    return text


def expiry_from_url(url: str) -> tuple[int | None, int | None]:
    """
    (expires_at epoch seconds, seconds-from-now) for a query whose `e` is an
    ABSOLUTE timestamp — mxdrop's convention.

    Do not feed a pkembed URL here: its `e` is a lifetime (`43200`), and read as
    an epoch that is 1970, which would call a live file expired. Nine to eleven
    digits is what separates the two conventions, and each function rejects the
    other's shape rather than guessing.
    """
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(url or "").query)
    raw = (query.get("e") or query.get("expires") or query.get("exp") or [""])[0]
    if not re.fullmatch(r"\d{9,11}", raw or ""):
        return None, None
    expires_at = int(raw)
    return expires_at, expires_at - int(time.time())


def duration_expiry_from_url(url: str) -> tuple[int | None, int | None]:
    """
    (expires_at, seconds-from-now) for a query whose `s` is the issue epoch and
    whose `e` is a lifetime in seconds — pkembed's convention.

    Measured on the live host: `s` equalled the clock at unpack time
    (`s - now = 0`) and `e` was `43200`, so the window is `s + e - now`, twelve
    hours from issue. `v` (a view counter), `sp` and `i` (player settings) carry
    no expiry meaning and are ignored here.
    """
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(url or "").query)
    start = (query.get("s") or [""])[0]
    lifetime = (query.get("e") or [""])[0]
    if not re.fullmatch(r"\d{9,11}", start or ""):
        return None, None
    if not re.fullmatch(r"\d{1,7}", lifetime or ""):
        return None, None
    expires_at = int(start) + int(lifetime)
    return expires_at, expires_at - int(time.time())


def signature_params(url: str) -> dict:
    """
    Which signed query keys the endpoint carries, values masked.

    The parameter *names* are the diagnostic ("is this URL temporary?"); the
    tokens themselves are never returned, so a verdict can be logged or written
    into raw_meta without storing a credential-shaped string.
    """
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(url or "").query)
    return {name: "present" for name in sorted(query)
            if name in SIGNED_QUERY_KEYS}


# ---------------------------------------------------------------------------
# Recognition
# ---------------------------------------------------------------------------

def _matches(url: str, host_re, path_re) -> bool:
    parts = urllib.parse.urlsplit(absolutize(url))
    host = (parts.netloc or "").lower()
    if not host or not host_re.search(host):
        return False
    return bool(path_re.match(parts.path or "/"))


def is_mxdrop_embed(url: str) -> bool:
    return _matches(url, MXDROP_HOST_RE, MXDROP_CONTENT_RE)


def is_pkembed_embed(url: str) -> bool:
    return _matches(url, PKEMBED_HOST_RE, PKEMBED_CONTENT_RE)


def vidbolt_parse_url(url: str) -> dict | None:
    """
    Parse a Vidbolt embed or page URL into its content locator:
    returns {"type": "movie"|"tv", "tmdb_id": str, "season": str|None, "episode": str|None}.
    """
    clean = (url or "").strip()
    parts = urllib.parse.urlsplit(clean if "://" in clean else f"https:{clean}")
    host = (parts.hostname or "").lower()
    if not host or not VIDBOLT_HOST_RE.search(host):
        return None
    match = VIDBOLT_CONTENT_RE.match(parts.path or "/")
    if not match:
        return None
    path_lower = (parts.path or "").lower()
    is_tv = "/tv/" in path_lower
    tmdb_id, season, episode = match.groups()
    return {
        "type": "tv" if is_tv else "movie",
        "tmdb_id": tmdb_id,
        "season": season if is_tv else None,
        "episode": episode if is_tv else None,
    }


def is_vidbolt_embed(url: str) -> bool:
    return vidbolt_parse_url(url) is not None


def is_vibuxer_embed(url: str) -> bool:
    clean = (url or "").replace("\t", "").strip()
    return _matches(clean, VIBUXER_HOST_RE, VIBUXER_CONTENT_RE)


def vidrift_parse_url(url: str) -> dict | None:
    """
    Parse a Vidrift embed URL:
    returns {"type": "movie"|"tv", "tmdb_id": str, "season": str|None, "episode": str|None}.
    """
    clean = (url or "").strip()
    parts = urllib.parse.urlsplit(clean if "://" in clean else f"https:{clean}")
    host = (parts.hostname or "").lower()
    if not host or not VIDRIFT_HOST_RE.search(host):
        return None
    match = VIDRIFT_CONTENT_RE.match(parts.path or "/")
    if not match:
        return None
    path_lower = (parts.path or "").lower()
    is_tv = "/tv/" in path_lower
    tmdb_id, season, episode = match.groups()
    return {
        "type": "tv" if is_tv else "movie",
        "tmdb_id": tmdb_id,
        "season": season if is_tv else None,
        "episode": episode if is_tv else None,
    }


def is_vidrift_embed(url: str) -> bool:
    return vidrift_parse_url(url) is not None


def iqsmart_parse_url(url: str) -> dict | None:
    """
    Parse an iqsmart embed URL:
    returns {"type": "movie"|"tv", "id": str, "season": str|None, "episode": str|None, "key": str}.
    """
    clean = (url or "").strip()
    parts = urllib.parse.urlsplit(clean if "://" in clean else f"https:{clean}")
    host = (parts.hostname or "").lower()
    if not host or not IQSMART_HOST_RE.search(host):
        return None
    match = IQSMART_CONTENT_RE.match(parts.path or "/")
    if not match:
        return None
    is_tv = "/tv/" in (parts.path or "").lower()
    title_id, season, episode = match.groups()
    params = urllib.parse.parse_qs(parts.query)
    key = params.get("key", [""])[0]
    return {
        "type": "tv" if is_tv else "movie",
        "id": title_id,
        "season": season if is_tv else None,
        "episode": episode if is_tv else None,
        "key": key,
    }


def is_iqsmart_embed(url: str) -> bool:
    return iqsmart_parse_url(url) is not None


def filmu_parse_url(url: str) -> dict | None:
    """
    Parse a Filmu or Vidly embed/page URL:
    returns {"type": "movie"|"tv", "tmdb_id": str, "season": str|None, "episode": str|None}.
    """
    clean = (url or "").strip()
    parts = urllib.parse.urlsplit(clean if "://" in clean else f"https:{clean}")
    host = (parts.hostname or "").lower()
    if not host or not FILMU_HOST_RE.search(host):
        return None
    match = FILMU_CONTENT_RE.match(parts.path or "/")
    if not match:
        return None
    is_tv = "/tv/" in (parts.path or "").lower()
    tmdb_id, season, episode = match.groups()
    return {
        "type": "tv" if is_tv else "movie",
        "tmdb_id": tmdb_id,
        "season": season if is_tv else None,
        "episode": episode if is_tv else None,
    }


def is_filmu_embed(url: str) -> bool:
    return filmu_parse_url(url) is not None


def cineverse_parse_url(url: str) -> dict | None:
    """
    Parse a Cineverse/Modiplay embed URL:
    returns {"type": "movie"|"tv", "tmdb_id": str, "season": str|None, "episode": str|None}.
    """
    clean = (url or "").strip()
    parts = urllib.parse.urlsplit(clean if "://" in clean else f"https:{clean}")
    host = (parts.hostname or "").lower()
    if not host or not CINEVERSE_HOST_RE.search(host):
        return None
    if not CINEVERSE_CONTENT_RE.match(parts.path or "/"):
        return None
    is_tv = "/tv" in (parts.path or "").lower()
    params = urllib.parse.parse_qs(parts.query)
    tmdb_id = params.get("id", [""])[0]
    if not tmdb_id:
        return None
    season = params.get("s", ["1"])[0] if is_tv else None
    episode = params.get("e", ["1"])[0] if is_tv else None
    return {
        "type": "tv" if is_tv else "movie",
        "tmdb_id": tmdb_id,
        "season": season,
        "episode": episode,
    }


def is_cineverse_embed(url: str) -> bool:
    return cineverse_parse_url(url) is not None


def gdrive_file_id(url: str) -> str:
    """
    The Drive file id a URL names, or "" when it names none.

    Both published shapes are read — `?id=` on the download endpoint and
    `/file/d/<id>/view` on the viewer — and the candidate is validated by
    character class and length before anything uses it, because this is the one
    field this module copies into a request to google.com.
    """
    parts = urllib.parse.urlsplit(absolutize(url))
    if not GDRIVE_HOST_RE.search((parts.netloc or "").lower()):
        return ""
    candidate = (urllib.parse.parse_qs(parts.query).get("id") or [""])[0]
    if not candidate:
        bits = [bit for bit in parts.path.split("/") if bit]
        if len(bits) >= 3 and bits[:2] == ["file", "d"]:
            candidate = bits[2]
    return candidate if GDRIVE_ID_RE.fullmatch(candidate or "") else ""


def is_gdrive_link(url: str) -> bool:
    return bool(gdrive_file_id(url))


def is_animahd_player(url: str) -> bool:
    return _matches(url, ANIMAHD_HOST_RE, ANIMAHD_PLAYER_PATH_RE)


def animahd_player_file_id(url: str) -> str:
    """The `file_id=` a player URL carries, or "" when it carries none."""
    parts = urllib.parse.urlsplit(absolutize(url))
    if not ANIMAHD_HOST_RE.search((parts.netloc or "").lower()):
        return ""
    candidate = (urllib.parse.parse_qs(parts.query).get("file_id") or [""])[0]
    return candidate if re.fullmatch(r"[A-Za-z0-9_-]{6,}", candidate or "") else ""


def gdrive_download_url(file_id: str) -> str:
    """
    The durable identifier for one Drive file: the download endpoint and its id.

    `file_id` arrives from `gdrive_file_id`, which already rejected anything
    outside a URL-safe character class, so it is interpolated rather than
    encoded — a forged id cannot reach here through this module's own parser.
    """
    return f"{GDRIVE_DOWNLOAD_PAGE}?export=download&id={file_id}"


def drive_confirm_form(html: str) -> str:
    """
    The URL a "Virus scan warning" page asks the browser to replay, or "".

    Google hands a large file's bytes over by making the client resubmit a
    hidden form, so the fields are read as they are published and never
    invented. The form's own action host is checked against GDRIVE_BYTE_HOSTS
    first: a page's action is the page's data, not an instruction about where
    this module sends its next request.
    """
    for match in GDRIVE_FORM_RE.finditer(html or ""):
        action = absolutize(match.group("action") or "")
        host = (urllib.parse.urlsplit(action).netloc or "").lower()
        if not any(host == name or host.endswith("." + name) for name in GDRIVE_BYTE_HOSTS):
            continue
        fields = {}
        for tag in GDRIVE_INPUT_RE.findall(match.group("body") or ""):
            attrs = {found.group("name").lower(): found.group("value")
                     for found in GDRIVE_ATTR_RE.finditer(tag)}
            if attrs.get("type", "").lower() == "hidden" and attrs.get("name"):
                fields[attrs["name"]] = attrs.get("value", "")
        if fields:
            return f"{action}?{urllib.parse.urlencode(fields)}"
    return ""


# ---------------------------------------------------------------------------
# The shared resolve chain: embed page -> config -> media -> probe verdict
# ---------------------------------------------------------------------------

def _new_result(service: str, embed_url: str) -> dict:
    return {"service": service, "embed_url": absolutize(embed_url), "final_url": "",
            "is_temporary": True, "expires_in": None, "status": "unverified",
            "notes": [], "poster_url": "", "signed_params": [], "subtitles": [],
            "sources": [], "quality": ""}


def _withheld_referrer(result: dict, referer: str | None) -> None:
    """
    Record the referrer policy against what the caller offered.

    No request this module makes carries a Referer: mxdrop 403s on the catalog
    site's, and pkembed's CDN tolerates it, so one rule serves both. A caller
    that passes the page URL anyway therefore changes nothing — except that a
    referrer from a host known to break the probe is named in `notes`, so the
    verdict explains itself instead of silently discarding the argument.
    """
    if referer and any(token in referer.lower() for token in FORBIDDEN_REFERRERS):
        result["notes"].append(
            "referrer withheld: this host 403s on the catalog site's referer")


def _unpack_embed_page(fetch, result: dict) -> str:
    """The packed script text of the embed page; failures are recorded in `result`."""
    status, body, _headers, _final = fetch(result["embed_url"])
    if status != 200:
        result["status"] = "dead" if status in (404, 410) else (
            "blocked" if status in (401, 403, 429) else "unknown")
        result["notes"].append(f"embed page HTTP {status}")
        return ""
    page = body if isinstance(body, str) else (body or b"").decode("utf-8", "replace")
    config = find_packed_config(page)
    if not config:
        result["status"] = "unknown"
        result["notes"].append("embed page carries no recognisable packed config")
    return config


def _finish_media(result: dict, fetch, verify: bool,
                  req_headers: dict | None = None) -> dict:
    """Expiry + signature names, then the Range probe when the caller asked for one."""
    if result["expires_in"] is None:
        result["notes"].append("signed query carries no parsable expiry")
    if not verify:
        result["notes"].append("unpacked only; the byte endpoint was not probed")
        return result
    probe = probe_range(result["final_url"], fetch=fetch, req_headers=req_headers)
    result["http_status"] = probe["http_status"]
    result["content_type"] = probe["content_type"]
    result["size_bytes"] = probe["size_bytes"]
    result["status"] = probe["status"]
    if probe["status"] == "active":
        if probe["reason"]:
            result["notes"].append(probe["reason"])
        return result
    if probe["status"] == "blocked":
        alive = host_is_alive(result["poster_url"], fetch=fetch)
        if alive is True:
            result["notes"].append("media refused while the host's poster answers: "
                                   "signature expired or referer policy")
        elif alive is False:
            result["status"] = "dead"
            result["notes"].append("media and poster both refused: host no longer serves this file")
        else:
            result["notes"].append(f"media refused ({probe['reason']}), poster unavailable")
    else:
        result["notes"].append(probe["reason"] or f"media HTTP {probe['http_status']}")
    return result


# ---------------------------------------------------------------------------
# mxdrop
# ---------------------------------------------------------------------------

def unwrap_mxdrop(embed_url: str, fetch=None, verify: bool = True,
                  referer: str | None = None) -> dict:
    """
    Embed URL -> {final_url, service, is_temporary, expires_in, status, notes, …}.

    `verify=False` unpacks without touching the byte endpoint (status
    `unverified`), which is what a polite crawl uses; `verify=True` adds one
    Range request and upgrades the status to what the host actually answered.
    The mp4 URL is a return value, never a stored value.
    """
    fetch = fetch or http_request
    result = _new_result(SERVICE_MXDROP, embed_url)
    _withheld_referrer(result, referer)
    if not is_mxdrop_embed(result["embed_url"]):
        result["status"] = "unknown"
        result["notes"].append("not an mxdrop embed URL")
        return result

    config = _unpack_embed_page(fetch, result)
    if not config:
        return result
    fields = parse_mdcore(config)
    wurl = absolutize(str(fields.get("wurl") or ""))
    if not wurl or not wurl.lower().startswith("https:"):
        result["status"] = "unknown"
        result["notes"].append("MDCore.wurl is absent or not an https endpoint")
        return result
    result["final_url"] = wurl
    result["poster_url"] = absolutize(str(fields.get("poster") or ""))
    result["vfile"] = str(fields.get("vfile") or "")
    result["vserver"] = str(fields.get("vserver") or "")
    for item in fields.get("sublangs") or []:
        if isinstance(item, (list, tuple)) and len(item) == 2:
            result["subtitles"].append({"language": item[0], "url": absolutize(item[1])})
    subs_param = urllib.parse.parse_qs(urllib.parse.urlsplit(wurl).query).get("subs")
    if subs_param:
        result["subtitles"].append({"language": "subs", "url": absolutize(subs_param[0])})

    # mxdrop publishes one rendition and no label for it; `sources` keeps the
    # same shape as pkembed's so a caller can treat either verdict alike.
    result["sources"] = [{"url": wurl, "mime": "", "label": ""}]

    _expires_at, result["expires_in"] = expiry_from_url(wurl)
    result["signed_params"] = sorted(signature_params(wurl))
    return _finish_media(result, fetch, verify)


def container_magic(body) -> str:
    """
    The video container named by a response's first bytes, or "" when they name none.

    Google Drive serves every file as `application/octet-stream`, so a content-type
    test cannot see the film that is definitely there; what it can see is the
    container header. EBML covers `.mkv` and `.webm` alike, and `ftyp` at offset 4
    is the ISO base-media family (`.mp4`, `.m4v`, `.mov`). Anything else stays
    unrecognised rather than being guessed at from the file name.
    """
    data = body if isinstance(body, bytes) else (body or "").encode("utf-8", "ignore")
    if data[:4] == b"\x1a\x45\xdf\xa3":
        return "matroska"
    if data[4:8] == b"ftyp":
        return "mp4"
    return ""


def is_hls_stream(content_type: str, magic: str, body: bytes | str) -> bool:
    """
    True when content_type or first bytes indicate an HLS playlist/stream.
    """
    ct = (content_type or "").lower()
    if any(h in ct for h in ("application/vnd.apple.mpegurl", "application/x-mpegurl", "audio/mpegurl")):
        return True
    data = body if isinstance(body, bytes) else (body or "").encode("utf-8", "ignore")
    return data.startswith(b"#EXTM3U")


def probe_range(url: str, size: int = RANGE_PROBE_BYTES,
                fetch=http_request, req_headers: dict | None = None) -> dict:
    """
    Ask the byte endpoint for the first `size` bytes and report what came back.

    206 + video/* is the answer that matters: the file exists and the signature
    is live. A plain 200 is recorded as `active` too but flagged `full_body`,
    because a host that ignores Range is telling us something a client should
    know before it plans a seek. A `video/*` type is not the only proof of video
    though — see `container_magic`, without which a Drive file can never be
    probed at all however well it streams. An HLS master (`#EXTM3U` / `application/vnd.apple.mpegurl`)
    is also active streaming media.
    """
    h = {"Range": f"bytes=0-{size - 1}"}
    if req_headers:
        h.update(req_headers)
    status, body, headers, final_url = fetch(
        url, headers=h, method="GET")
    content_type = (headers.get("content-type") or "").split(";")[0].strip().lower()
    total = None
    content_range = headers.get("content-range") or ""
    match = re.search(r"/(\d+)\s*$", content_range)
    if match:
        total = int(match.group(1))
    verdict = {"status": "unknown", "http_status": status, "content_type": content_type,
               "size_bytes": total, "final_url": final_url, "reason": ""}
    magic = container_magic(body)
    is_hls = is_hls_stream(content_type, magic, body)
    if status == 0:
        verdict["status"] = "error"
        verdict["reason"] = str(body)[:200]
    elif status == 206:
        if content_type.startswith("video/") or magic or is_hls:
            verdict["status"] = "active"
            if content_type.startswith("video/"):
                verdict["reason"] = ""
            elif is_hls:
                verdict["reason"] = f"206 {content_type} holds an HLS stream"
            else:
                verdict["reason"] = f"206 {content_type} holds a {magic} container"
        else:
            verdict["reason"] = f"206 {content_type}"
    elif status == 200:
        if content_type.startswith("video/") or magic or is_hls:
            verdict["status"] = "active"
            if content_type.startswith("video/"):
                verdict["reason"] = "full_body"
            elif is_hls:
                verdict["reason"] = f"full_body, {content_type} holds an HLS stream"
            else:
                verdict["reason"] = f"full_body, {content_type} holds a {magic} container"
            if total is None:
                verdict["size_bytes"] = len(body) if isinstance(body, (bytes, str)) else None
        else:
            verdict["status"] = "blocked"
            verdict["reason"] = f"200 {content_type}"
    elif status in (401, 403, 429):
        verdict["status"] = "blocked"
        verdict["reason"] = f"HTTP {status}"
    elif status in (404, 410):
        verdict["status"] = "dead"
        verdict["reason"] = f"HTTP {status}"
    elif 500 <= status <= 599:
        verdict["status"] = "error"
        verdict["reason"] = f"HTTP {status}"
    else:
        verdict["status"] = "error"
        verdict["reason"] = f"HTTP {status}"
    return verdict


def host_is_alive(poster_url: str, fetch=http_request) -> bool | None:
    """
    True / False from the host's own poster, None when the poster cannot answer.

    The poster is unsigned, so it separates "the signature expired" (poster 200,
    media 403) from "the host went away" (neither answers).
    """
    if not poster_url:
        return None
    status, _body, headers, _final = fetch(poster_url)
    content_type = (headers.get("content-type") or "").split(";")[0].strip().lower()
    return status == 200 and (content_type.startswith("image/") or not content_type)


# ---------------------------------------------------------------------------
# pkembed
# ---------------------------------------------------------------------------

def pkembed_renditions(config: str) -> list[dict]:
    """
    Every `<source>` the unpacked player call publishes, in the host's own order.

    The tags carry the label the host itself uses ("360p 414 kbps"), which is
    worth keeping because it is the only quality statement either host makes.
    When a page carries no `<source>` tags the media URLs are scanned out of the
    script directly, since that is what a different player build on the same
    host was seen to do; a URL is only a rendition if its path ends in a media
    extension, so an ad tag or a poster can never become one.
    """
    renditions = []
    for tag in PK_SOURCE_TAG_RE.findall(config or ""):
        attrs = {name.lower(): value for name, value in PK_ATTR_RE.findall(tag)}
        url = absolutize(attrs.get("src", ""))
        if url and MEDIA_URL_RE.fullmatch(url):
            renditions.append({"url": url, "mime": attrs.get("type", ""),
                               "label": attrs.get("title", "")})
    if renditions:
        return renditions
    scanned = [absolutize(found) for found in MEDIA_URL_RE.findall(config or "")]
    return [{"url": url, "mime": "", "label": ""} for url in dict.fromkeys(scanned)
            if MEDIA_URL_RE.fullmatch(url)]


def select_rendition(renditions: list[dict]) -> dict | None:
    """
    The file to hand back: `_l/l.mp4` first, `_n/n.mp4` next, then whatever came.

    Which rendition is "better" is not ours to decide — on the measured posts
    the `_l` tag was titled 360p and the `_n` tag 480p, so a size ranking would
    pick the opposite file from the one the host's own player loads. The order
    here is the owner's, and every rendition stays in `sources` so the client
    can choose.
    """
    for suffix in ("/l.mp4", "/n.mp4"):
        for item in renditions:
            if urllib.parse.urlsplit(item["url"]).path.lower().endswith(suffix):
                return item
    return renditions[0] if renditions else None


def unwrap_pkembed(embed_url: str, fetch=None, verify: bool = True,
                   referer: str | None = None) -> dict:
    """
    Embed URL -> {final_url, service, is_temporary, expires_in, status, notes, …}.

    Same contract as `unwrap_mxdrop`: the signed media URL is a return value and
    must not be persisted, the embed URL is the durable identifier, and
    `verify=False` unpacks without touching the byte endpoint. The differences
    are the base-36 packer, `<source>` renditions instead of `MDCore.wurl`, and
    an expiry that is `s + e` rather than `e`.
    """
    fetch = fetch or http_request
    result = _new_result(SERVICE_PKEMBED, embed_url)
    _withheld_referrer(result, referer)
    if not is_pkembed_embed(result["embed_url"]):
        result["status"] = "unknown"
        result["notes"].append("not a pkembed embed URL")
        return result

    config = _unpack_embed_page(fetch, result)
    if not config:
        return result
    renditions = pkembed_renditions(config)
    if not renditions:
        result["status"] = "unknown"
        result["notes"].append("unpacked script publishes no media URL")
        return result
    chosen = select_rendition(renditions)
    result["final_url"] = chosen["url"]
    result["sources"] = renditions
    result["quality"] = chosen["label"]
    result["poster_url"] = absolutize((PK_POSTER_RE.search(config) or ["", ""])[1])
    for found in PK_SUB_RE.findall(config):
        result["subtitles"].append({"language": "subtitle", "url": absolutize(found)})

    _expires_at, result["expires_in"] = duration_expiry_from_url(result["final_url"])
    result["signed_params"] = sorted(signature_params(result["final_url"]))
    return _finish_media(result, fetch, verify)


def _drive_probe(result: dict, fetch) -> dict:
    """
    One bounded probe of the byte endpoint, with Drive's quota read as a quota.

    A 403/429/503 from Google means this file has hit its per-day download limit
    — it says nothing about whether the file exists, and a resolver that retried
    it would spend the whole client's standing on one episode. So the attempt is
    made once and the verdict stops at `unverified`.
    """
    result["signed_params"] = sorted(signature_params(result["final_url"]))
    result = _finish_media(result, fetch, True)
    if result.get("http_status") in (403, 429, 503, 0):
        result["status"] = "unverified"
        result["notes"].append(
            f"HTTP {result['http_status']} from Drive: a per-file download quota or a "
            "transport failure, recorded as unverified rather than retried")
    return result


def unwrap_gdrive(url: str, fetch=None, verify: bool = True,
                  referer: str | None = None) -> dict:
    """
    Drive file URL -> {final_url, service, is_temporary, status, notes, …}.

    The contract is the same as the packer hosts', with two differences that come
    from Drive being a file store rather than a player: `verify=False` sends
    **no request at all** (there is no packer to unpack and the file id is
    already the durable identifier, so a cataloging crawl costs Drive nothing),
    and `verify=True` never spends more than the two requests the interstitial
    needs. The replayed form URL carries a per-page `uuid` and is therefore
    marked temporary; the redirect target of a small public file is not.
    """
    fetch = fetch or http_request
    result = _new_result(SERVICE_GDRIVE, url)
    _withheld_referrer(result, referer)
    file_id = gdrive_file_id(result["embed_url"])
    if not file_id:
        result["status"] = "unknown"
        result["notes"].append("not a Google Drive file URL")
        return result
    result["file_id"] = file_id
    result["embed_url"] = gdrive_download_url(file_id)
    result["final_url"] = result["embed_url"]
    result["is_temporary"] = False
    if not verify:
        result["notes"].append("file id cataloged without a request: Drive's quota is "
                               "spent by probing, not by storing")
        return result

    status, body, headers, final_url = fetch(result["embed_url"])
    content_type = (headers.get("content-type") or "").split(";")[0].strip().lower()
    if status in (404, 410):
        result["status"] = "dead"
        result["notes"].append(f"Drive holds no file {file_id} (HTTP {status})")
        return result
    if status in (403, 429, 503) or status == 0:
        result["status"] = "unverified"
        result["notes"].append(f"download endpoint HTTP {status}: a per-file quota or a "
                               "transport failure, not a verdict about the file")
        return result

    page = body if isinstance(body, str) else (body or b"").decode("utf-8", "replace")
    if "html" in content_type or "<html" in page[:2000].lower():
        replay = drive_confirm_form(page)
        if not replay:
            result["status"] = "blocked"
            result["notes"].append("Drive answered with a page that publishes no "
                                   "download form: the file is not public")
            return result
        result["notes"].append("large file: the download endpoint answered with its "
                               "confirmation page, replayed once")
        result["final_url"] = replay
        result["is_temporary"] = True
        result["sources"] = [{"url": replay, "mime": "application/octet-stream",
                              "label": ""}]
        return _drive_probe(result, fetch)

    # A small public file answers with a redirect to its bytes, so no second
    # request was needed to find the endpoint — the probe below is the one that
    # proves they are video.
    byte_url = absolutize(final_url) or result["embed_url"]
    result["final_url"] = byte_url
    result["sources"] = [{"url": byte_url, "mime": content_type, "label": ""}]
    result["notes"].append("public file: the download endpoint led straight to its bytes")
    return _drive_probe(result, fetch)


# ---------------------------------------------------------------------------
# animahd player — two page GETs and one Range request, no JS engine
# ---------------------------------------------------------------------------

def _page_text(body) -> str:
    return body if isinstance(body, str) else (body or b"").decode("utf-8", "replace")


def animahd_target(page: str) -> tuple[str, str]:
    """
    (`secure page URL`, `file id`) the player page tells its own browser to open.

    The host label is copied out of the page rather than rebuilt: two files on
    this site were measured and they redirect to different hosts
    (`theultimateanimehub` and `animeepisodesandmore`), so a constant here would
    resolve one file and break the next. `?id=` is the same value the catalog row
    published as `data-fileid`, which is what makes the mismatch check in
    `unwrap_animahd` worth doing at all.
    """
    found = ANIMAHD_TARGET_RE.search(page or "")
    if not found:
        return "", ""
    return f"https://{found.group(1)}animahd.fun/?id={found.group(2)}", found.group(2)


def animahd_renditions(page: str) -> list[dict]:
    """
    The secure page's `<source>` tags that really are byte endpoints.

    "Really are" is a structural test, not a filename test: https, a host under
    `workers.dev`, and a query carrying both `eid` and `token`. The tag's own
    `type="video/mp4"` is kept as `declared_mime` and trusted for nothing — the
    same tag's URL ends in `ext=.mp4` while the host answers `video/x-matroska`
    with EBML bytes, so the extension and the declaration are the two least
    reliable strings on the page.
    """
    renditions = []
    for tag in re.findall(r"<source\b[^>]*>", page or "", re.I | re.S):
        src = ANIMAHD_SOURCE_RE.search(tag)
        if not src:
            continue
        url = absolutize(src.group(1))
        parts = urllib.parse.urlsplit(url)
        query = urllib.parse.parse_qs(parts.query)
        if not url.lower().startswith("https:"):
            continue
        if not ANIMAHD_WORKER_RE.search((parts.netloc or "").lower()):
            continue
        if not (query.get("eid") and query.get("token")):
            continue
        declared = re.search(r"""\btype\s*=\s*["']([^"']*)["']""", tag, re.I)
        renditions.append({"url": url, "mime": "", "label": "",
                           "declared_mime": (declared.group(1) if declared else "").lower()})
    return renditions


def unwrap_animahd(url: str, fetch=None, verify: bool = True,
                   referer: str | None = None) -> dict:
    """
    Player URL -> {final_url, service, is_temporary, expires_in, status, notes, …}.

    Same contract as the other resolvers, with one addition worth naming: the
    durable identifier is the *player* URL, because the secure host varies per
    file and the worker URL is re-signed per load. `verify=False` spends nothing
    — the catalog already holds everything that lasts. `verify=True` spends three
    requests and never more: player page, secure page, one Range probe.

    Every request here must carry a User-Agent. The secure host was measured
    answering 403 to a request that had none and 200 to the same request with a
    normal browser UA and no Referer at all; `http_request` supplies the UA header
    and this module never attaches a Referer to a media request, so both halves
    of that measurement are satisfied by the seam rather than by caller care.
    """
    fetch = fetch or http_request
    result = _new_result(SERVICE_ANIMAHD, url)
    _withheld_referrer(result, referer)
    if not is_animahd_player(result["embed_url"]):
        result["status"] = "unknown"
        result["notes"].append("not an animahd player URL")
        return result
    result["file_id"] = animahd_player_file_id(result["embed_url"])
    if not verify:
        result["final_url"] = result["embed_url"]
        result["notes"].append("player URL cataloged without a request: the byte URL "
                               "is re-signed per play, so this URL is all that lasts")
        return result

    status, body, _headers, _final = fetch(result["embed_url"])
    page = _page_text(body)
    if status != 200:
        result["status"] = ("dead" if status in (404, 410)
                            else "blocked" if status in (401, 403, 429) else "unknown")
        result["notes"].append(f"player page HTTP {status}")
        return result

    target, target_id = animahd_target(page)
    if not target:
        result["status"] = "unknown"
        result["notes"].append("player page publishes no <host>.animahd.fun/?id= target")
        return result
    if result["file_id"] and target_id != result["file_id"]:
        result["notes"].append(f"player page redirects to file id {target_id}, which is "
                               f"not the {result['file_id']} the row named")
    result["bridge_url"] = target

    status, body, _headers, _final = fetch(target)
    secure = _page_text(body)
    if status != 200:
        result["status"] = ("dead" if status in (404, 410)
                            else "blocked" if status in (401, 403, 429) else "unknown")
        result["notes"].append(
            f"secure page HTTP {status}"
            + (" — this host answers 403 to a request that carries no User-Agent"
               if status in (401, 403) else ""))
        return result

    renditions = animahd_renditions(secure)
    if not renditions:
        result["status"] = "blocked" if ANIMAHD_LOCKED_RE.search(secure) else "unknown"
        result["notes"].append(
            "secure page publishes no byte endpoint"
            + (" — its own words are the Google quota lock, so this file is "
               "rate-limited right now, not gone" if ANIMAHD_LOCKED_RE.search(secure) else ""))
        return result
    result["final_url"] = renditions[0]["url"]
    result["sources"] = renditions

    _expires_at, measured = expiry_from_url(result["final_url"])
    if measured is None:
        result["expires_in"] = ANIMAHD_TOKEN_SECONDS
        result["notes"].append(
            f"the signed query carries no expiry of its own; {ANIMAHD_TOKEN_SECONDS} s "
            "is claimed from the measured window, which is at least 32 minutes and "
            "whose ceiling nobody has observed")
    else:
        result["expires_in"] = measured
    result["signed_params"] = sorted(signature_params(result["final_url"]))
    result = _finish_media(result, fetch, True)

    content_type = (result.get("content_type") or "").lower()
    if content_type.startswith("video/"):
        mime = content_type
    else:
        mime = ANIMAHD_MIME
        if result["status"] != "active":
            result["notes"].append(
                f"mime reported as the measured {ANIMAHD_MIME}: this call did not get a "
                "video content type back from the byte host")
    for item in result["sources"]:
        item["mime"] = mime
    # `content_type` stays whatever the host actually answered, even when that
    # answer is nothing or `text/html`: the caller can then see that the mime in
    # `sources` is the measured one, not a claim about this particular response.

    # A refusal from this host is a token or a quota answer, never a verdict about
    # the file: the token is minted per load and the secure page itself explains
    # that Google's per-file limit can be exhausted. One attempt, no retry — a
    # resolver that hammered it would spend the client's standing on one episode.
    if result.get("http_status") in (403, 429, 503, 0):
        result["status"] = "unverified"
        result["notes"].append(
            f"HTTP {result['http_status']} from the byte host: an expired token, a "
            "Google quota, or a transport failure — recorded unverified, not retried")
    elif result["status"] == "active":
        for item in result["sources"]:
            if item["declared_mime"] and item["declared_mime"] != mime:
                result["notes"].append(
                    f"the page declares {item['declared_mime']}, the host answers {mime}")
                break
    return result


# ---------------------------------------------------------------------------
# Vidbolt & Vibuxer
# ---------------------------------------------------------------------------

def unwrap_vibuxer(embed_url: str, fetch=None, verify: bool = True,
                   referer: str | None = None) -> dict:
    """
    Embed URL -> {final_url, service, is_temporary, expires_in, status, notes, …}.

    Vibuxer serves an embed page containing packed JavaScript (Dean Edwards).
    Unpacking the script yields a JSON object with HLS master playlist URL(s)
    and subtitle tracks.
    """
    fetch = fetch or http_request
    clean_url = (embed_url or "").replace("\t", "").strip()
    result = _new_result(SERVICE_VIBUXER, clean_url)
    _withheld_referrer(result, referer)
    if not is_vibuxer_embed(clean_url):
        result["status"] = "unknown"
        result["notes"].append("not a vibuxer embed URL")
        return result

    config = _unpack_embed_page(fetch, result)
    if not config:
        return result

    m3u8s = re.findall(
        r"""["'](https?://[^\s"'<>]+\.m3u8[^\s"'<>]*)["']""",
        config,
        re.I,
    )
    if not m3u8s:
        result["status"] = "unknown"
        result["notes"].append("unpacked script publishes no m3u8 media URL")
        return result

    result["final_url"] = m3u8s[0]
    result["sources"] = [{"url": u, "mime": "application/vnd.apple.mpegurl", "label": "HLS"} for u in dict.fromkeys(m3u8s)]
    result["quality"] = "HLS"
    for found in PK_SUB_RE.findall(config):
        result["subtitles"].append({"language": "subtitle", "url": absolutize(found)})

    _expires_at, result["expires_in"] = duration_expiry_from_url(result["final_url"])
    result["signed_params"] = sorted(signature_params(result["final_url"]))
    return _finish_media(result, fetch, verify)


def unwrap_vidbolt(url: str, fetch=None, verify: bool = True,
                   referer: str | None = None) -> dict:
    """
    Embed or movie/tv URL -> {final_url, service, is_temporary, expires_in, status, notes, …}.

    Vidbolt resolves streams via JSON API: /api/resolve?type=<movie|tv>&id=<tmdb_id>[&season=S&episode=E].
    The API returns HLS sources and subtitles.
    """
    fetch = fetch or http_request
    clean_url = (url or "").strip()
    result = _new_result(SERVICE_VIDBOLT, clean_url)
    _withheld_referrer(result, referer)
    parsed = vidbolt_parse_url(clean_url)
    if not parsed:
        result["status"] = "unknown"
        result["notes"].append("not a vidbolt embed or content URL")
        return result

    tmdb_id = parsed["tmdb_id"]
    content_type = parsed["type"]
    api_path = f"/api/resolve?type={content_type}&id={tmdb_id}"
    if content_type == "tv":
        season = parsed["season"] or "1"
        episode = parsed["episode"] or "1"
        api_path += f"&season={season}&episode={episode}"

    api_url = f"https://vidbolt.xyz{api_path}"
    result["bridge_url"] = api_url
    status, body, headers, final_url = fetch(api_url, headers={"Referer": "https://vidbolt.xyz/"})
    if status != 200:
        result["status"] = ("dead" if status in (404, 410)
                            else "blocked" if status in (401, 403, 429) else "unknown")
        result["notes"].append(f"vidbolt api HTTP {status}")
        return result

    try:
        data = json.loads(body.decode("utf-8", "replace") if isinstance(body, (bytes, bytearray)) else body)
    except Exception as e:
        result["status"] = "unknown"
        result["notes"].append(f"vidbolt api JSON parse error: {e}")
        return result

    stream = data.get("stream")
    if not stream or not isinstance(stream, dict):
        result["status"] = "dead"
        result["notes"].append("vidbolt api returned no stream for this content")
        return result

    raw_sources = stream.get("sources", [])
    if not raw_sources:
        result["status"] = "dead"
        result["notes"].append("vidbolt api returned empty sources list")
        return result

    renditions = []
    for s in raw_sources:
        if isinstance(s, dict) and s.get("url"):
            renditions.append({
                "url": s["url"],
                "mime": "application/vnd.apple.mpegurl" if (s.get("kind") == "hls" or ".m3u8" in s["url"]) else "video/mp4",
                "label": s.get("quality") or s.get("kind") or "HLS",
            })

    if not renditions:
        result["status"] = "dead"
        result["notes"].append("vidbolt api sources contained no valid URLs")
        return result

    result["final_url"] = renditions[0]["url"]
    result["sources"] = renditions
    result["quality"] = renditions[0]["label"]

    _expires_at, measured_exp = duration_expiry_from_url(result["final_url"])
    result["expires_in"] = measured_exp if measured_exp is not None else VIDBOLT_DEFAULT_EXPIRY_SECONDS
    result["signed_params"] = sorted(signature_params(result["final_url"]))
    return _finish_media(result, fetch, verify)


def unwrap_vidrift(url: str, fetch=None, verify: bool = True,
                   referer: str | None = None) -> dict:
    """
    Vidrift embed URL -> {final_url, service, is_temporary, expires_in, status, notes, …}.

    Embed page holds `var embedMeta = {...};` containing `orionStreams` (HLS/MP4)
    and subtitle tracks. Probing media endpoints requires `Referer: https://embed.vidrift.net/`.
    """
    fetch = fetch or http_request
    clean_url = (url or "").strip()
    result = _new_result(SERVICE_VIDRIFT, clean_url)
    _withheld_referrer(result, referer)
    parsed = vidrift_parse_url(clean_url)
    if not parsed:
        result["status"] = "unknown"
        result["notes"].append("not a vidrift embed URL")
        return result

    status, body, headers, final_url = fetch(
        clean_url, headers={"Referer": "https://embed.vidrift.net/"})
    if status != 200:
        result["status"] = ("dead" if status in (404, 410)
                            else "blocked" if status in (401, 403, 429) else "unknown")
        result["notes"].append(f"vidrift embed page HTTP {status}")
        return result

    page = body if isinstance(body, str) else (body or b"").decode("utf-8", "replace")
    m = re.search(r"var\s+embedMeta\s*=\s*(\{.*?\});", page, re.DOTALL)
    if not m:
        result["status"] = "unknown"
        result["notes"].append("vidrift page holds no embedMeta")
        return result

    try:
        meta = json.loads(m.group(1))
    except Exception as e:
        result["status"] = "unknown"
        result["notes"].append(f"vidrift embedMeta JSON error: {e}")
        return result

    orion_streams = meta.get("orionStreams", [])
    if not orion_streams:
        result["status"] = "dead"
        result["notes"].append("vidrift publishes no active streams for this title")
        return result

    renditions = []
    for s in orion_streams:
        s_url = s.get("url") or ""
        if s_url.startswith("/"):
            s_url = f"https://embed.vidrift.net{s_url}"
        mime = "application/vnd.apple.mpegurl" if (s.get("type") == "hls" or ".m3u8" in s_url) else "video/mp4"
        renditions.append({
            "url": s_url,
            "mime": mime,
            "label": s.get("name") or s.get("type", "stream").upper(),
        })

    primary = next((r for r in renditions if r["mime"] == "application/vnd.apple.mpegurl"), renditions[0])
    result["final_url"] = primary["url"]
    result["sources"] = renditions
    result["quality"] = primary["label"]

    for sub in meta.get("bigbangSubtitles", []):
        sub_url = sub.get("url")
        if sub_url:
            result["subtitles"].append({
                "language": sub.get("label") or sub.get("lang") or "subtitle",
                "url": f"https://embed.vidrift.net{sub_url}" if sub_url.startswith("/") else sub_url,
            })

    _expires_at, result["expires_in"] = duration_expiry_from_url(result["final_url"])
    result["signed_params"] = sorted(signature_params(result["final_url"]))
    return _finish_media(result, fetch, verify, req_headers={"Referer": "https://embed.vidrift.net/"})


def unwrap_iqsmart(url: str, fetch=None, verify: bool = True,
                   referer: str | None = None) -> dict:
    """
    iqsmart embed URL -> {final_url, service, is_temporary, expires_in, status, notes, …}.

    iqsmart resolves via:
    1. /mymovieapi or /myseriesapi -> fileslug
    2. https://pro.iqsmartgames.com/embedhelper2.php -> base64 mresult
    3. Decode mresult -> Hanerix slug (smwh)
    4. Fetch Hanerix embed -> Dean Edwards unpack -> .m3u8 HLS master
    """
    fetch = fetch or http_request
    clean_url = (url or "").strip()
    result = _new_result(SERVICE_IQSMART, clean_url)
    _withheld_referrer(result, referer)
    parsed = iqsmart_parse_url(clean_url)
    if not parsed:
        result["status"] = "unknown"
        result["notes"].append("not an iqsmart embed URL")
        return result

    title_id = parsed["id"]
    id_param = "imdbid" if title_id.startswith("tt") else "tmdbid"
    key = parsed["key"]
    if parsed["type"] == "tv":
        season = parsed["season"] or "1"
        episode = parsed["episode"] or "1"
        api_url = f"https://streams.iqsmartgames.com/myseriesapi?{id_param}={title_id}&season={season}&epname={episode}&key={key}"
    else:
        api_url = f"https://streams.iqsmartgames.com/mymovieapi?{id_param}={title_id}&key={key}"

    result["bridge_url"] = api_url
    status, body, headers, final_url = fetch(
        api_url, headers={"Referer": "https://streams.iqsmartgames.com/"})
    if status != 200:
        result["status"] = ("dead" if status in (404, 410)
                            else "blocked" if status in (401, 403, 429) else "unknown")
        result["notes"].append(f"iqsmart api HTTP {status}")
        return result

    try:
        api_data = json.loads(body.decode("utf-8", "replace") if isinstance(body, (bytes, bytearray)) else body)
    except Exception as e:
        result["status"] = "unknown"
        result["notes"].append(f"iqsmart api JSON error: {e}")
        return result

    data_list = api_data.get("data", [])
    if not data_list or not isinstance(data_list, list):
        result["status"] = "dead"
        result["notes"].append("iqsmart api returned no media data for this title")
        return result

    fileslug = data_list[0].get("fileslug")
    if not fileslug:
        result["status"] = "dead"
        result["notes"].append("iqsmart api data item missing fileslug")
        return result

    helper_url = "https://pro.iqsmartgames.com/embedhelper2.php"
    helper_payload = urllib.parse.urlencode({
        "sid": fileslug,
        "UserFavSite": "",
        "currentDomain": '["pro.iqsmartgames.com"]',
    }).encode("utf-8")
    try:
        h_status, h_body, h_headers, _ = fetch(
            helper_url,
            headers={
                "Referer": "https://pro.iqsmartgames.com/",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
            data=helper_payload,
        )
    except TypeError:
        h_status, h_body, h_headers, _ = fetch(
            helper_url,
            headers={
                "Referer": "https://pro.iqsmartgames.com/",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
    if h_status != 200:
        result["status"] = "dead" if h_status in (404, 410) else "unknown"
        result["notes"].append(f"iqsmart embedhelper2 HTTP {h_status}")
        return result

    try:
        h_json = json.loads(h_body.decode("utf-8", "replace") if isinstance(h_body, (bytes, bytearray)) else h_body)
    except Exception as e:
        result["status"] = "unknown"
        result["notes"].append(f"iqsmart helper JSON error: {e}")
        return result

    mresult = h_json.get("mresult")
    if not mresult:
        result["status"] = "dead"
        result["notes"].append("iqsmart embedhelper2 returned no mresult")
        return result

    try:
        decoded_map = json.loads(base64.b64decode(mresult).decode("utf-8", "replace"))
    except Exception as e:
        result["status"] = "unknown"
        result["notes"].append(f"iqsmart mresult decode error: {e}")
        return result

    han_id = decoded_map.get("smwh")
    if not han_id:
        result["status"] = "unknown"
        result["notes"].append(f"iqsmart mresult contains no hanerix backend (keys: {list(decoded_map.keys())})")
        return result

    han_url = f"https://hanerix.com/e/{han_id}"
    han_status, han_body, _, _ = fetch(han_url, headers={"Referer": "https://pro.iqsmartgames.com/"})
    if han_status != 200:
        result["status"] = "dead" if han_status in (404, 410) else "unknown"
        result["notes"].append(f"hanerix embed HTTP {han_status}")
        return result

    han_page = han_body if isinstance(han_body, str) else (han_body or b"").decode("utf-8", "replace")
    unpacked = find_packed_config(han_page)
    if not unpacked:
        result["status"] = "unknown"
        result["notes"].append("hanerix embed page holds no packed config")
        return result

    m3u8s = re.findall(
        r"""["'](https?://[^\s"'<>]+\.m3u8[^\s"'<>]*)["']""",
        unpacked,
        re.I,
    )
    if not m3u8s:
        result["status"] = "unknown"
        result["notes"].append("hanerix script publishes no m3u8 stream")
        return result

    result["final_url"] = m3u8s[0]
    result["sources"] = [{"url": u, "mime": "application/vnd.apple.mpegurl", "label": "HLS"} for u in dict.fromkeys(m3u8s)]
    result["quality"] = "HLS"

    _expires_at, result["expires_in"] = duration_expiry_from_url(result["final_url"])
    result["signed_params"] = sorted(signature_params(result["final_url"]))
    return _finish_media(result, fetch, verify, req_headers={"Referer": "https://hanerix.com/"})


def unwrap_filmu(url: str, fetch=None, verify: bool = True,
                 referer: str | None = None) -> dict:
    """
    Filmu/Vidly embed URL -> {final_url, service, is_temporary, expires_in, status, notes, …}.

    Filmu embed redirects or renders via Vidly, publishing a signed HLS stream URL.
    Probing media endpoints requires `Referer: https://vidly.pro/`.
    """
    fetch = fetch or http_request
    clean_url = (url or "").strip()
    result = _new_result(SERVICE_FILMU, clean_url)
    _withheld_referrer(result, referer)
    parsed = filmu_parse_url(clean_url)
    if not parsed:
        result["status"] = "unknown"
        result["notes"].append("not a filmu or vidly embed URL")
        return result

    status, body, headers, final_url = fetch(
        clean_url, headers={"Referer": "https://vidly.pro/"})
    if status != 200:
        result["status"] = ("dead" if status in (404, 410)
                            else "blocked" if status in (401, 403, 429) else "unknown")
        result["notes"].append(f"filmu page HTTP {status}")
        return result

    page = body if isinstance(body, str) else (body or b"").decode("utf-8", "replace")
    m3u8s = re.findall(r"""https?://[^\s"'<>]+\.m3u8[^\s"'<>]*""", page)
    if not m3u8s:
        result["status"] = "dead"
        result["notes"].append("filmu page publishes no m3u8 stream")
        return result

    clean_m3u8 = m3u8s[0].replace(r"\u0026", "&").replace("&amp;", "&").rstrip("\\")
    result["final_url"] = clean_m3u8
    result["sources"] = [{"url": clean_m3u8, "mime": "application/vnd.apple.mpegurl", "label": "HLS"}]
    result["quality"] = "HLS"

    _expires_at, result["expires_in"] = duration_expiry_from_url(result["final_url"])
    result["signed_params"] = sorted(signature_params(result["final_url"]))
    return _finish_media(result, fetch, verify, req_headers={"Referer": "https://vidly.pro/"})


def unwrap_cineverse(url: str, fetch=None, verify: bool = True,
                     referer: str | None = None) -> dict:
    """
    Cineverse embed URL -> {final_url, service, is_temporary, expires_in, status, notes, …}.

    Cineverse uses proxy.php (Bingr/Vidrift backend) to resolve streams.
    If direct Vidrift stream is available, resolves it.
    If Vidbolt fallback embed is offered, resolves via unwrap_vidbolt.
    """
    fetch = fetch or http_request
    clean_url = (url or "").strip()
    result = _new_result(SERVICE_CINEVERSE, clean_url)
    _withheld_referrer(result, referer)
    parsed = cineverse_parse_url(clean_url)
    if not parsed:
        result["status"] = "unknown"
        result["notes"].append("not a cineverse embed URL")
        return result

    tmdb_id = parsed["tmdb_id"]
    if parsed["type"] == "tv":
        s = parsed["season"] or "1"
        e = parsed["episode"] or "1"
        c_param = f"{tmdb_id}:tv:{s}:{e}"
    else:
        c_param = f"{tmdb_id}:movie:0:0"

    proxy_url = f"https://rozgarlelo.modiplay.xyz/proxy.php?p=bingr&c={c_param}&noredirect=1"
    result["bridge_url"] = proxy_url
    status, body, headers, _ = fetch(proxy_url, headers={"Referer": clean_url})
    if status != 200:
        result["status"] = ("dead" if status in (404, 410)
                            else "blocked" if status in (401, 403, 429) else "unknown")
        result["notes"].append(f"cineverse proxy HTTP {status}")
        return result

    page = body if isinstance(body, str) else (body or b"").decode("utf-8", "replace")
    m_src = re.search(r"""var\s+(?:directSrc|src)\s*=\s*['"]([^'"]+)['"]""", page)
    if m_src:
        src = m_src.group(1).replace(r"\/", "/")
        full_src = urllib.parse.urljoin(proxy_url, src)
        if "vidrift.net" in full_src or "/stream_proxy.php" in full_src or ".m3u8" in full_src:
            result["final_url"] = full_src
            result["sources"] = [{"url": full_src, "mime": "application/vnd.apple.mpegurl", "label": "HLS"}]
            result["quality"] = "HLS"
            _expires_at, result["expires_in"] = duration_expiry_from_url(result["final_url"])
            result["signed_params"] = sorted(signature_params(result["final_url"]))
            return _finish_media(result, fetch, verify, req_headers={"Referer": "https://embed.vidrift.net/"})

    # Check fallback EMBED_URL (e.g. vidbolt)
    m_embed = re.search(r"""var\s+EMBED_URL\s*=\s*['"]([^'"]+)['"]""", page)
    if m_embed:
        embed_target = m_embed.group(1).replace(r"\/", "/")
        if is_vidbolt_embed(embed_target):
            vb_verdict = unwrap_vidbolt(embed_target, fetch=fetch, verify=verify)
            vb_verdict["service"] = SERVICE_CINEVERSE
            vb_verdict["notes"].insert(0, f"cineverse chained through vidbolt: {embed_target}")
            return vb_verdict

    result["status"] = "dead"
    result["notes"].append("cineverse proxy returned neither active vidrift stream nor supported embed")
    return result


def main(argv: list[str] | None = None) -> int:
    """One URL in, one JSON verdict out — a manual check of the chain."""
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print(__doc__.strip().splitlines()[0])
        print("usage: host_resolvers.py <embed-url> [--no-verify]")
        return 2
    url = args[0]
    if is_pkembed_embed(url):
        unwrap = unwrap_pkembed
    elif is_vibuxer_embed(url):
        unwrap = unwrap_vibuxer
    elif is_vidbolt_embed(url):
        unwrap = unwrap_vidbolt
    elif is_vidrift_embed(url):
        unwrap = unwrap_vidrift
    elif is_iqsmart_embed(url):
        unwrap = unwrap_iqsmart
    elif is_filmu_embed(url):
        unwrap = unwrap_filmu
    elif is_cineverse_embed(url):
        unwrap = unwrap_cineverse
    elif is_gdrive_link(url):
        unwrap = unwrap_gdrive
    elif is_animahd_player(url):
        unwrap = unwrap_animahd
    else:
        unwrap = unwrap_mxdrop
    verdict = unwrap(url, verify="--no-verify" not in args)
    print(json.dumps(verdict, indent=2, ensure_ascii=False))
    return 0 if verdict["status"] in ("active", "unverified") else 1


if __name__ == "__main__":
    sys.exit(main())
