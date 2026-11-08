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
import hashlib
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
#
# Session 103 (2026-11-08): the same packed config is served by the
# mixdrop family the catalog actually stores — `mixdrop.ag/f/<id>` (the file
# page) 302s to `mxdrop.click/f/<id>`, and `mxdrop.click/e/<id>` carries the
# identical packer (`MDCore.wurl` → signed .mp4, verified live: the unpacked
# URL answered 206 video/mp4). `mixdrop.ag/e/<id>` 302s to the same embed.
# The host rule therefore covers both spellings and the live TLDs (.ag,
# .click); the catalog's `mixdrop` service rows resolve through the same
# `unwrap_mxdrop` once the resolver rewrites `/f/` to `/e/`.
MXDROP_HOST_RE = re.compile(r"(?:^|\.)(?:mxdrop|mixdrop)\.(?:to|top|click|ag)$", re.I)
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
SERVICE_GOFILE = "gofile"
SERVICE_STREAMTAPE = "streamtape"
SERVICE_STREAM = "stream"
SERVICE_STREAMWISH = "streamwish"
SERVICE_VOE = "voe"
SERVICE_VIDHIDE = "vidhide"
SERVICE_VIDMOLY = "vidmoly"
SERVICE_UPLOADFLIX = "uploadflix"
SERVICE_1XPLAYER = "1xplayer"
SERVICE_MOVIEBOX = "moviebox"

# uploadflix (Session 104b, verified live 2026-11-08): a generic XFS file
# host. The file page (dl.uploadflix.com/<id> 302s to 1uploadflix.net/f/<id>)
# already carries the download2 form AND the storage-host dllink anchor, so
# the common path is one GET + one Range probe; the download1/download2 form
# POSTs are the fallback for a page that shows the form first. The dllink
# lives on a storage host with a self-signed certificate (curl -k / an
# unverified SSL context is the only way the probe succeeds), and its token
# rotates on every page load — the link is a result of this call, never
# stored durably, and the resolver re-unwraps on every press.
UPLOADFLIX_HOST_RE = re.compile(r"(?:^|\.)(?:dl\.uploadflix\.com|1uploadflix\.net)$", re.I)
UPLOADFLIX_FORM_RE = re.compile(
    r"""<form\b[^>]*>(?P<body>.*?)</form>""", re.I | re.S)
UPLOADFLIX_INPUT_RE = re.compile(
    r"""<input\b[^>]*?\bname\s*=\s*["'](?P<name>[^"']+)["'][^>]*?(?:\bvalue\s*=\s*["'](?P<value>[^"']*)["'])?""",
    re.I)
# The dllink anchor: an href on a host other than the file host, path /d/<long
# token>/<filename>. The filename carries spaces unencoded in the href, so the
# value is read whole (single- or double-quoted) and quoted before requesting.
UPLOADFLIX_DLLINK_RE = re.compile(
    r"""href\s*=\s*["'](?P<url>https?://[^"'\s<>]+/d/[A-Za-z0-9_-]{20,}/[^"']*)["']""",
    re.I)
UPLOADFLIX_VIDEO_EXTS = (".mp4", ".mkv", ".webm", ".mov", ".avi", ".m3u8")

# 1xplayer (Session 104b, verified live 2026-11-08): the play page carries
# `let p3 = {"file":"~<per-load>", "key":"<64-char per-load>", ...}` and the
# player POSTs /playlist/<file-minus-~>.txt with X-CSRF-TOKEN = key, which
# answers a single signed master URL. The master, its variants and its
# segments are signed to the requesting IP with a ~2h expiry AND gated on
# Referer: the play page — a bare master GET 404s, with the Referer it
# answers 200 #EXTM3U with 4 variants. The resolver MUST re-resolve per
# play and NEVER cache the master URL. The `file`/`key` values are per-load
# and the play host rotates (vd.1xplayer.com -> geoxe446syt.com, streams on
# salov447hev.com), so nothing about the host is pinned.
XPLAYER_HOST_RE = re.compile(r"(?:^|\.)(?:vd\.)?1xplayer\.com$", re.I)
XPLAYER_FILE_RE = re.compile(r'''"file"\s*:\s*"([^"]+)"''')
XPLAYER_KEY_RE = re.compile(r'''"key"\s*:\s*"([^"]+)"''')
XPLAYER_MASTER_EXPIRY_RE = re.compile(r":(\d{10}):")
XPLAYER_VARIANT_RE = re.compile(
    r"""#EXT-X-STREAM-INF:[^\n]*RESOLUTION=\d+x(\d+)[^\n]*\n([^\n#][^\n]*)""")
XPLAYER_SEGMENT_RE = re.compile(r"""^([^\n#][^\n]*?\.ts(?:\?[^\n\s]*)?)\s*$""", re.M)

# MovieBox (Session 104b, verified live 2026-11-08): themoviebox.xyz and
# 123moviesfree.club are the same MovieBox frontend on the shared aoneroom
# backend. Detail pages are trailers-only; the playable route is the signed
# play API, which answers full MP4 streams ONLY when called with
# Referer = the /movies/ player-page URL — the same call from /detail/
# (or with no Referer) returns streams:[] even with session cookies, and
# plain HTTP with NO cookies at all returns the streams when the Referer
# is the /movies/ URL, so the Referer is the discriminator and no cookie
# jar is needed. themoviebox gives 360p+480p MP4 free (1080p vipLocked);
# 123moviesfree gives 480p+1080p free. DASH is vipLocked and needs an
# Edge-Cache-Cookie + X-MB-Token, so it is never taken. NEVER probe a
# signed URL with HEAD (the CDN answers 429) — GET Range only.
MOVIEBOX_HOST_RE = re.compile(
    r"(?:^|\.)(?:themoviebox\.xyz|123moviesfree\.club)$", re.I)
MOVIEBOX_DETAIL_RE = re.compile(
    r"^/(?:detail|movies)/([^/?#]+)", re.I)

# gofile (Session 103, verified live 2026-11-08): the real website token is
# generated client-side as sha256(UA :: language :: accountToken ::
# 4h-window :: salt), salt embedded in gofile.io/dist/js/wt.obf.js. The
# static token in config.js is a decoy and the token must travel in the
# X-Website-Token HEADER — the query-param form still answers
# error-notPremium. The salt rotates (Mar-Aug 2026 rotations on record);
# the value below is the one verified live 2026-11-08, and a persistent
# error-notPremium means it rotated and this constant needs updating.
# The UA hashed into the token MUST be the UA sent on the request, so gofile
# has its own UA string (Windows Chrome/126, the reference client's), not
# this module's Linux one.
GOFILE_API = "https://api.gofile.io"
GOFILE_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
GOFILE_LANGUAGE = "en-US"
GOFILE_WT_SALT = "12af056dacea0b"
GOFILE_WT_WINDOW_SECONDS = 14400  # 4-hour rotating window
GOFILE_TIMEOUT = 10
GOFILE_ID_RE = re.compile(r"(?:gofile\.io/(?:d/)?)([A-Za-z0-9]+)", re.I)
GOFILE_VIDEO_EXTS = (".mp4", ".mkv", ".webm", ".m3u8", ".mov", ".avi")

# streamtape (Session 103, verified live 2026-11-08): the embed page carries
# three hidden link divs and a script that REBUILDS two of them with string
# surgery. The raw `#ideoooolink` div is a decoy — its id is wrong and the
# URL it names answers {"status":500}. The `#norobotlink` (and
# `#captchalink`) rebuilds evaluate to the true signed get_video URL, which
# answers 206 video/mp4 on a bare Range probe. Only those two are read.
STREAMTAPE_LINK_RE = re.compile(
    r"""getElementById\('(\w+link)'\)\.innerHTML\s*=\s*'([^']*)'\s*\+\s*\(?'([^']*)'\)"""
    r"""\.substring\((\d+)\)(?:\.substring\((\d+)\))?""")

# Packer video hosts of the streamwish family (Session 103, verified live
# 2026-11-08 on watch-online.mom, service "stream"): one GET of the embed
# page, unpack the P.A.C.K.E.R. block with the repo's own unpacker, read the
# HLS master out of the decoded JS. `hls2` is the absolute master.m3u8;
# `hls4` is a bare path that is rebuilt against the embed host (streamflix
# v1.7.117: domainless hls4 links are always rebuilt). The media probe must
# carry Referer: the embed URL — the host 403s without it.
PACKER_HLS2_RE = re.compile(r'"hls2"\s*:\s*"([^"]+)"')
PACKER_HLS4_RE = re.compile(r'"hls4"\s*:\s*"([^"]+)"')
PACKER_FILE_RE = re.compile(r'"file"\s*:\s*"([^"]+)"')

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
                 method: str = "GET", follow: bool = True,
                 data: bytes | None = None):
    """
    (status, body, headers, final_url) for one request.

    A redirect that was asked not to be followed comes back as its 3xx with the
    Location in `headers`; a transport failure comes back as status 0 with the
    reason in the body, because a resolver's job is to name what it saw.
    """
    fields = {"User-Agent": USER_AGENT}
    fields.update(headers or {})
    request = urllib.request.Request(url, headers=fields, method=method,
                                     data=data)
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


def _cookie_jar_fetch():
    """A fetch with the http_request return shape that keeps cookies.

    The XFS form flow is a session: the download2 POST is the same session
    the file page opened. Plain http_request is stateless, so a host that
    checks the session cookie would refuse the POST; the jar makes the
    flow match the browser's. One jar per call — nothing persists between
    unwraps.
    """
    import http.cookiejar

    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=_SSL_CONTEXT),
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def _fetch(url, headers=None, timeout=DEFAULT_TIMEOUT, method="GET",
               follow=True, data=None):
        fields = {"User-Agent": USER_AGENT}
        fields.update(headers or {})
        request = urllib.request.Request(url, headers=fields, method=method,
                                         data=data)
        try:
            with opener.open(request, timeout=timeout) as response:
                return (int(response.status), response.read(PROBE_READ_BYTES),
                        {k.lower(): v for k, v in response.getheaders()},
                        response.geturl())
        except urllib.error.HTTPError as exc:
            return (int(exc.code), exc.read(PROBE_READ_BYTES),
                    {k.lower(): v for k, v in (exc.headers.items() if exc.headers else [])},
                    url)
        except Exception as exc:                  # DNS, TLS, timeout, refused
            return 0, str(exc), {}, url

    return _fetch


# The uploadflix storage host (cloud.secure-storage.top:8080) serves a
# self-signed certificate: the default context fails the handshake and the
# probe would call a live file dead. This context is used ONLY for the Range
# probe of a dllink this module just extracted from the host's own page —
# never for a page fetch, never for a URL a caller supplied.
_UNVERIFIED_CONTEXT = ssl._create_unverified_context()


def _unverified_fetch(url, headers=None, timeout=DEFAULT_TIMEOUT,
                      method="GET", follow=True, data=None):
    """http_request's shape over the unverified context (see above)."""
    fields = {"User-Agent": USER_AGENT}
    fields.update(headers or {})
    request = urllib.request.Request(url, headers=fields, method=method,
                                     data=data)
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=_UNVERIFIED_CONTEXT))
    try:
        with opener.open(request, timeout=timeout) as response:
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


def _finish_media(result: dict, fetch, verify: bool) -> dict:
    """Expiry + signature names, then the Range probe when the caller asked for one."""
    if result["expires_in"] is None:
        result["notes"].append("signed query carries no parsable expiry")
    if not verify:
        result["notes"].append("unpacked only; the byte endpoint was not probed")
        return result
    probe = probe_range(result["final_url"], fetch=fetch)
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


def probe_range(url: str, size: int = RANGE_PROBE_BYTES,
                fetch=http_request) -> dict:
    """
    Ask the byte endpoint for the first `size` bytes and report what came back.

    206 + video/* is the answer that matters: the file exists and the signature
    is live. A plain 200 is recorded as `active` too but flagged `full_body`,
    because a host that ignores Range is telling us something a client should
    know before it plans a seek. A `video/*` type is not the only proof of video
    though — see `container_magic`, without which a Drive file can never be
    probed at all however well it streams.
    """
    status, body, headers, final_url = fetch(
        url, headers={"Range": f"bytes=0-{size - 1}"}, method="GET")
    content_type = (headers.get("content-type") or "").split(";")[0].strip().lower()
    total = None
    content_range = headers.get("content-range") or ""
    match = re.search(r"/(\d+)\s*$", content_range)
    if match:
        total = int(match.group(1))
    verdict = {"status": "unknown", "http_status": status, "content_type": content_type,
               "size_bytes": total, "final_url": final_url, "reason": ""}
    magic = container_magic(body)
    if status == 0:
        verdict["status"] = "error"
        verdict["reason"] = str(body)[:200]
    elif status == 206:
        if content_type.startswith("video/") or magic:
            verdict["status"] = "active"
            verdict["reason"] = "" if content_type.startswith("video/") \
                else f"206 {content_type} holds a {magic} container"
        else:
            verdict["reason"] = f"206 {content_type}"
    elif status == 200:
        if content_type.startswith("video/") or magic:
            verdict["status"] = "active"
            verdict["reason"] = "full_body" if content_type.startswith("video/") \
                else f"full_body, {content_type} holds a {magic} container"
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


def _gofile_website_token(account_token: str, window_offset: int = 0) -> str:
    """sha256(UA :: language :: accountToken :: 4h-window :: salt)."""
    window = int(time.time() // GOFILE_WT_WINDOW_SECONDS) + window_offset
    raw = (f"{GOFILE_USER_AGENT}::{GOFILE_LANGUAGE}::{account_token}::"
           f"{window}::{GOFILE_WT_SALT}")
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _gofile_content_id(url: str) -> str:
    """The content id out of a gofile page URL, or the bare id itself."""
    match = GOFILE_ID_RE.search(url or "")
    if match:
        return match.group(1)
    candidate = (url or "").strip()
    if re.fullmatch(r"[A-Za-z0-9]{6,}", candidate):
        return candidate
    return ""


def _gofile_pick_child(children) -> dict | None:
    """The file to hand back: a video file first (biggest), else the largest file."""
    if isinstance(children, dict):
        files = list(children.values())
    elif isinstance(children, list):
        files = children
    else:
        files = []
    files = [c for c in files if isinstance(c, dict) and c.get("link")
             and (c.get("type") or "file") == "file"]
    if not files:
        return None
    videos = [c for c in files
              if (c.get("name") or "").lower().endswith(GOFILE_VIDEO_EXTS)]
    pool = videos if videos else files
    return max(pool, key=lambda c: int(c.get("size") or 0))


def _gofile_contents(fetch, content_id: str, token: str,
                     window_offset: int = 0):
    """One /contents call: (status, parsed-json-or-None, error-string)."""
    headers = {
        "Authorization": "Bearer " + token,
        "X-Website-Token": _gofile_website_token(token, window_offset),
        "X-BL": GOFILE_LANGUAGE,
        "User-Agent": GOFILE_USER_AGENT,
        "Accept": "*/*",
        "Origin": "https://gofile.io",
        "Referer": "https://gofile.io/",
    }
    url = (f"{GOFILE_API}/contents/{content_id}?page=1&pageSize=1000"
           "&sortField=createTime&sortDirection=-1")
    status, body, _headers, _final = fetch(url, headers=headers,
                                            timeout=GOFILE_TIMEOUT)
    if status == 0:
        return 0, None, str(body)[:200]
    try:
        return status, json.loads(_page_text(body)), ""
    except Exception:
        return status, None, "contents answer is not JSON"


def unwrap_gofile(url: str, fetch=None, verify: bool = True) -> dict:
    """
    gofile page URL -> {final_url, service, is_temporary, expires_in, status, notes, …}.

    Light-speed chain (verified live 2026-11-08): POST /accounts for a guest
    token, GET /contents/<id> with the computed website token in the
    X-Website-Token header, one auth'd Range probe of the picked file. No page
    fetch, no JS. The bare direct link 302s without the Authorization header,
    so the probe that proves the file MUST carry it — a bare probe is not a
    proof here, it is a redirect. The token is never persisted: the next press
    re-unwraps with a fresh guest token (the cached bare link 302s and is
    treated as stale, exactly like any other expired signature).

    A folder with no video file answers `unknown` (nothing playable), never a
    zip as a "playable" file: the resolver's verdict contract only accepts
    `active`, and a zip never probes active.
    """
    fetch = fetch or http_request
    result = _new_result(SERVICE_GOFILE, url)
    content_id = _gofile_content_id(result["embed_url"])
    if not content_id:
        result["status"] = "unknown"
        result["notes"].append("not a gofile content URL")
        return result
    result["file_id"] = content_id

    status, body, _headers, _final = fetch(
        f"{GOFILE_API}/accounts", method="POST",
        headers={"User-Agent": GOFILE_USER_AGENT, "Origin": "https://gofile.io"},
        timeout=GOFILE_TIMEOUT)
    token = ""
    if status == 200:
        try:
            token = (json.loads(_page_text(body)).get("data") or {}).get("token") or ""
        except Exception:
            token = ""
    if not token:
        result["status"] = ("dead" if status in (404, 410)
                            else "blocked" if status in (401, 403, 429) else "unknown")
        result["notes"].append(f"guest account HTTP {status}")
        return result

    data = None
    for offset in (0, -1):
        status, parsed, error = _gofile_contents(fetch, content_id, token, offset)
        if status == 200 and isinstance(parsed, dict) and parsed.get("status") == "ok":
            data = parsed.get("data") or {}
            break
        if isinstance(parsed, dict) and parsed.get("status") == "error-notFound":
            result["status"] = "dead"
            result["notes"].append("gofile: content not found (folder deleted)")
            return result
        if isinstance(parsed, dict) and parsed.get("status") == "error-notPremium":
            continue  # previous 4h window, then the salt has rotated
        result["status"] = ("dead" if status in (404, 410)
                            else "blocked" if status in (401, 403, 429) else "unknown")
        result["notes"].append(f"contents HTTP {status}" + (f": {error}" if error else ""))
        return result
    if data is None:
        result["status"] = "unknown"
        result["notes"].append(
            "contents answers error-notPremium on both 4h windows: the website-token "
            "salt has rotated — update GOFILE_WT_SALT from the live wt.obf.js")
        return result

    child = _gofile_pick_child(data.get("children"))
    if child is None:
        result["status"] = "unknown"
        result["notes"].append("folder holds no file with a direct link")
        return result
    result["final_url"] = absolutize(str(child.get("link") or ""))
    result["sources"] = [{"url": result["final_url"], "mime": "",
                          "label": str(child.get("name") or "")}]
    if not result["final_url"].lower().startswith("https:"):
        result["status"] = "unknown"
        result["notes"].append("picked child carries no https direct link")
        return result
    if not verify:
        result["notes"].append("unpacked only; the byte endpoint was not probed")
        return result

    def _authed_fetch(url2, headers=None, timeout=DEFAULT_TIMEOUT,
                      method="GET", follow=True):
        merged = dict(headers or {})
        merged["Authorization"] = "Bearer " + token
        return fetch(url2, headers=merged, timeout=timeout,
                     method=method, follow=follow)

    return _finish_media(result, _authed_fetch, True)


# ---------------------------------------------------------------------------
# streamtape
# ---------------------------------------------------------------------------

def _streamtape_rebuild_link(page: str) -> str:
    """
    The true signed get_video URL out of the embed page, or "".

    The page's script rebuilds `#norobotlink` (and `#captchalink`) with
    substring surgery; the raw `#ideoooolink` div is a decoy whose id is
    wrong and whose URL answers {"status":500}. Only the rebuilt links are
    ever read, norobotlink first.
    """
    found = {}
    for match in STREAMTAPE_LINK_RE.finditer(page or ""):
        name, prefix, piece, first, second = (
            match.group(1), match.group(2), match.group(3),
            int(match.group(4)), match.group(5))
        rebuilt = piece[first:]
        if second:
            rebuilt = rebuilt[int(second):]
        found[name] = prefix + rebuilt
    for name in ("norobotlink", "captchalink"):
        url = found.get(name) or ""
        if url.startswith("//"):
            return "https:" + url
        if url.startswith("/"):
            return "https:/" + url
    return ""


def unwrap_streamtape(embed_url: str, fetch=None, verify: bool = True) -> dict:
    """
    streamtape embed/view URL -> {final_url, service, is_temporary, expires_in, status, notes, …}.

    Light-speed chain (verified live 2026-11-08): 1 GET of the embed page,
    evaluate the norobotlink JS rebuild, one bare Range probe of the signed
    get_video URL (206 video/mp4, no Referer needed). No wait, no captcha —
    the token is minted server-side into the page. The signed URL carries an
    `expires` timestamp, so it is used at once and never cached past expiry.
    """
    fetch = fetch or http_request
    result = _new_result(SERVICE_STREAMTAPE, embed_url)
    status, body, _headers, _final = fetch(result["embed_url"])
    if status != 200:
        result["status"] = ("dead" if status in (404, 410)
                            else "blocked" if status in (401, 403, 429) else "unknown")
        result["notes"].append(f"embed page HTTP {status}")
        return result
    link = _streamtape_rebuild_link(_page_text(body))
    if not link:
        result["status"] = "unknown"
        result["notes"].append("embed page carries no rebuildable get_video link")
        return result
    result["final_url"] = link
    result["sources"] = [{"url": link, "mime": "", "label": ""}]
    _expires_at, result["expires_in"] = expiry_from_url(link)
    result["signed_params"] = sorted(signature_params(link))
    return _finish_media(result, fetch, verify)


# ---------------------------------------------------------------------------
# Packer HLS hosts of the streamwish family (stream / streamwish)
# ---------------------------------------------------------------------------

def _probe_playlist_or_file(url: str, fetch, referer: str) -> dict:
    """
    The Range probe for a host whose answer may be a playlist, not a file.

    `probe_range` only calls a 206 `active` when the answer is video/* or a
    recognised container — an HLS master (206 application/vnd.apple.mpegurl,
    body starting #EXTM3U) is real playable media too, so it is accepted
    here with `is_playlist` set. Anything else follows probe_range's own
    status map, so a dead file and a blocked host are named the same way.
    """
    status, body, headers, final_url = fetch(
        url, headers={"Range": f"bytes=0-{RANGE_PROBE_BYTES - 1}",
                      "Referer": referer}, method="GET")
    content_type = (headers.get("content-type") or "").split(";")[0].strip().lower()
    total = None
    match = re.search(r"/(\d+)\s*$", headers.get("content-range") or "")
    if match:
        total = int(match.group(1))
    verdict = {"status": "unknown", "http_status": status,
               "content_type": content_type, "size_bytes": total,
               "final_url": final_url, "reason": "", "is_playlist": False}
    data = body if isinstance(body, bytes) else (body or "").encode("utf-8", "ignore")
    if status == 0:
        verdict["status"] = "error"
        verdict["reason"] = str(body)[:200]
    elif status in (200, 206):
        if "mpegurl" in content_type or "m3u8" in content_type \
                or data[:7] == b"#EXTM3U":
            verdict["status"] = "active"
            verdict["is_playlist"] = True
            verdict["reason"] = "HLS master playlist"
            if total is None:
                verdict["size_bytes"] = len(data)
        elif content_type.startswith("video/") or container_magic(data):
            verdict["status"] = "active"
            verdict["reason"] = ""
        else:
            verdict["reason"] = f"{status} {content_type}"
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


def unwrap_packer_hls(embed_url: str, service: str, fetch=None,
                      verify: bool = True) -> dict:
    """
    Packer embed URL -> {final_url, service, is_temporary, expires_in, status, notes, …}.

    One GET of the embed page, unpack the P.A.C.K.E.R. block with the repo's
    own unpacker, read the HLS master out of the decoded JS (`hls2` first,
    then a domainless `hls4` rebuilt against the embed host, then a `file`
    URL), one Range probe carrying Referer: the embed URL. The probe accepts
    an HLS master as playable media — that is the whole point of these hosts.
    `service` is the catalog's own label for the row ("stream",
    "streamwish"), so the verdict files under the name the DB already uses.
    """
    fetch = fetch or http_request
    result = _new_result(service, embed_url)
    status, body, _headers, _final = fetch(result["embed_url"])
    if status != 200:
        result["status"] = ("dead" if status in (404, 410)
                            else "blocked" if status in (401, 403, 429) else "unknown")
        result["notes"].append(f"embed page HTTP {status}")
        return result
    page = _page_text(body)
    config = find_packed_config(page)
    if not config:
        result["status"] = "unknown"
        result["notes"].append("embed page carries no recognisable packed config")
        return result
    media = ""
    match = PACKER_HLS2_RE.search(config)
    if match:
        media = match.group(1)
    if not media:
        match = PACKER_HLS4_RE.search(config)
        if match:
            raw = match.group(1)
            media = raw if raw.startswith("http") else (
                urllib.parse.urlsplit(result["embed_url"]).scheme + "://"
                + urllib.parse.urlsplit(result["embed_url"]).netloc + raw)
    if not media:
        match = PACKER_FILE_RE.search(config)
        if match:
            media = match.group(1)
    if not media:
        result["status"] = "unknown"
        result["notes"].append("unpacked config carries no hls2 / hls4 / file URL")
        return result
    result["final_url"] = absolutize(media)
    result["sources"] = [{"url": result["final_url"], "mime": "",
                          "label": "hls" if result["final_url"].endswith(".m3u8")
                          else ""}]
    _expires_at, result["expires_in"] = expiry_from_url(result["final_url"])
    result["signed_params"] = sorted(signature_params(result["final_url"]))
    if not verify:
        result["notes"].append("unpacked only; the byte endpoint was not probed")
        return result
    probe = _probe_playlist_or_file(result["final_url"], fetch,
                                    result["embed_url"])
    result["http_status"] = probe["http_status"]
    result["content_type"] = probe["content_type"]
    result["size_bytes"] = probe["size_bytes"]
    result["status"] = probe["status"]
    if probe["reason"]:
        result["notes"].append(probe["reason"])
    return result


# VOE (voe.sx + mirrors such as shannoncoldalready.com): the embed page
# carries an obfuscated payload (a base64-ish code) plus an external loader
# script holding the LUTs; the decode is pure stdlib (re + base64 + json).
# Flow ported from mhdzumair/mediaflow-proxy's VoeExtractor (which cites
# Gujal00/ResolveURL's voesx.py). Verified live 2026-11-08: the decoded
# `source` is an HLS master that Range-probes 206 application/vnd.apple.
# mpegurl. The voe.sx page itself is a JS redirect (window.location.href)
# to the mirror — followed once, the same way mediaflow-proxy does.
VOE_PAYLOAD_RE = re.compile(
    r"""json">\["([^"]+)"]</script>\s*<script\s*src="([^"]+)""", re.DOTALL)
VOE_LUTS_RE = re.compile(r"""(\[(?:'\W{2}'[,\]]){1,9})""", re.DOTALL)
VOE_REDIRECT_RE = re.compile(r"""window\.location\.href\s*=\s*'([^']+)""")


def voe_decode(code: str, luts: str) -> dict:
    """Undo VOE's obfuscation: ROT-shift the letters, strip the LUT
    characters, base64-decode, shift every char back by 3, reverse,
    base64-decode again. Returns the decoded JSON (which carries `source`)."""
    lut = ["".join([("\\" + x) if x in ".*+?^${}()|[]\\" else x for x in i])
           for i in luts[2:-2].split("','")]
    txt = ""
    for ch in code:
        x = ord(ch)
        if 64 < x < 91:
            x = (x - 52) % 26 + 65
        elif 96 < x < 123:
            x = (x - 84) % 26 + 97
        txt += chr(x)
    for entry in lut:
        txt = re.sub(entry, "", txt)
    decoded = base64.b64decode(txt).decode("utf-8")
    shifted = "".join(chr(ord(c) - 3) for c in decoded)
    return json.loads(base64.b64decode(shifted[::-1]).decode("utf-8"))


def unwrap_voe(embed_url: str, fetch=None, verify: bool = True) -> dict:
    """
    VOE embed URL -> {final_url, service, is_temporary, expires_in, status, notes, …}.

    One GET of the embed page (following the voe.sx JS redirect to the
    mirror once), one GET of the loader script the page names, decode the
    obfuscated payload, one Range probe of the decoded source (an HLS
    master; the probe accepts it as playable media). The decoded JSON also
    carries a `fallback` mp4 — used only when `source` is absent.
    """
    fetch = fetch or http_request
    result = _new_result(SERVICE_VOE, embed_url)
    page_url = result["embed_url"]
    for _hop in range(2):
        status, body, _headers, _final = fetch(page_url)
        if status != 200:
            result["status"] = ("dead" if status in (404, 410)
                                else "blocked" if status in (401, 403, 429)
                                else "unknown")
            result["notes"].append(f"embed page HTTP {status}")
            return result
        page = _page_text(body)
        match = VOE_PAYLOAD_RE.search(page)
        if match:
            break
        redir = VOE_REDIRECT_RE.search(page)
        if not redir:
            result["status"] = "unknown"
            result["notes"].append(
                "embed page carries no VOE payload and no redirect")
            return result
        page_url = urllib.parse.urljoin(page_url, redir.group(1))
        result["notes"].append("followed the voe.sx redirect to its mirror")
    else:
        result["status"] = "unknown"
        result["notes"].append("VOE payload not found after the mirror redirect")
        return result
    code, script_src = match.group(1), match.group(2)
    script_url = urllib.parse.urljoin(page_url, script_src)
    status, body, _headers, _final = fetch(script_url)
    if status != 200:
        result["status"] = "unknown"
        result["notes"].append(f"loader script HTTP {status}")
        return result
    luts_match = VOE_LUTS_RE.search(_page_text(body))
    if not luts_match:
        result["status"] = "unknown"
        result["notes"].append("loader script carries no LUTs")
        return result
    try:
        data = voe_decode(code, luts_match.group(1))
    except Exception as exc:  # noqa: BLE001 - a bad payload must not crash
        result["status"] = "unknown"
        result["notes"].append(f"VOE decode failed: {exc}")
        return result
    media = data.get("source") or data.get("fallback") or ""
    if not media:
        result["status"] = "unknown"
        result["notes"].append("decoded VOE payload carries no source URL")
        return result
    result["final_url"] = absolutize(media)
    result["sources"] = [{"url": result["final_url"], "mime": "",
                          "label": "hls" if result["final_url"].endswith(".m3u8")
                          else ""}]
    _expires_at, result["expires_in"] = expiry_from_url(result["final_url"])
    result["signed_params"] = sorted(signature_params(result["final_url"]))
    if not verify:
        result["notes"].append("decoded only; the byte endpoint was not probed")
        return result
    probe = _probe_playlist_or_file(result["final_url"], fetch, page_url)
    result["http_status"] = probe["http_status"]
    result["content_type"] = probe["content_type"]
    result["size_bytes"] = probe["size_bytes"]
    result["status"] = probe["status"]
    if probe["reason"]:
        result["notes"].append(probe["reason"])
    return result


# Vidhide rows point at filesforever.link/embed/<id>, which 302s to a
# pro.iqsmartgames.com /svid/ page carrying a `const sid`; one POST to
# embedhelper2.php (the same helper the StreamHG flow uses) returns the
# hanerix page URL, and the hanerix page carries a P.A.C.K.E.R. block
# whose hls2 is the master playlist.
VIDHIDE_SID_RE = re.compile(r"""const sid\s*=\s*"([^"]+)""")
VIDHIDE_HELPER_URL = "https://pro.iqsmartgames.com/embedhelper2.php"


def unwrap_vidhide(embed_url: str, fetch=None, verify: bool = True) -> dict:
    """
    Vidhide embed URL -> {final_url, service, is_temporary, expires_in, status, notes, …}.

    Five requests, no browser: GET the embed (302 to the /svid/ page),
    POST the sid to embedhelper2.php, GET the hanerix page it names,
    unpack the P.A.C.K.E.R. block, Range-probe the hls2 master. The
    hanerix page also lists other mirrors (rpmhub, p2pplay, uns.bio,
    morencius) — only the hanerix one carries the packer, so only it is
    followed. Verified live 2026-11-08 on row su9ss0k: Range probe 206
    application/vnd.apple.mpegurl. (The first row tried, y3b3kvy, maps
    the same chain but its master 502s — that file's CDN copy is dead,
    not the method.)
    """
    fetch = fetch or http_request
    result = _new_result(SERVICE_VIDHIDE, embed_url)
    status, body, _headers, final_url = fetch(result["embed_url"])
    if status != 200:
        result["status"] = ("dead" if status in (404, 410)
                            else "blocked" if status in (401, 403, 429)
                            else "unknown")
        result["notes"].append(f"embed page HTTP {status}")
        return result
    sid_match = VIDHIDE_SID_RE.search(_page_text(body))
    if not sid_match:
        result["status"] = "unknown"
        result["notes"].append("svid page carries no sid")
        return result
    form = urllib.parse.urlencode({
        "sid": sid_match.group(1), "UserFavSite": "",
        "currentDomain": json.dumps(["pro.iqsmartgames.com",
                                     "pro.iqsmartgames.com"])}).encode()
    status, body, _headers, _final = fetch(
        VIDHIDE_HELPER_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded",
                 "Referer": final_url},
        method="POST", data=form)
    if status != 200:
        result["status"] = ("dead" if status in (404, 410)
                            else "blocked" if status in (401, 403, 429)
                            else "unknown")
        result["notes"].append(f"embedhelper HTTP {status}")
        return result
    try:
        payload = json.loads(_page_text(body))
        decoded = json.loads(base64.b64decode(
            payload.get("mresult") or "").decode("utf-8"))
    except Exception:  # noqa: BLE001 - a bad helper answer must not crash
        result["status"] = "unknown"
        result["notes"].append("embedhelper answer is not the expected JSON")
        return result
    hanerix = ""
    for code, source in (payload.get("sources") or {}).items():
        site_url = (source or {}).get("siteUrl") or ""
        if "hanerix.com" in site_url and decoded.get(code):
            hanerix = site_url + decoded[code]
            break
    if not hanerix:
        result["status"] = "unknown"
        result["notes"].append("embedhelper answer carries no hanerix page")
        return result
    status, body, _headers, _final = fetch(
        hanerix, headers={"Referer": final_url})
    if status != 200:
        result["status"] = ("dead" if status in (404, 410)
                            else "blocked" if status in (401, 403, 429)
                            else "unknown")
        result["notes"].append(f"hanerix page HTTP {status}")
        return result
    config = find_packed_config(_page_text(body))
    if not config:
        result["status"] = "unknown"
        result["notes"].append(
            "hanerix page carries no recognisable packed config")
        return result
    media = ""
    match = PACKER_HLS2_RE.search(config)
    if match:
        media = match.group(1)
    if not media:
        match = PACKER_HLS4_RE.search(config)
        if match:
            raw = match.group(1)
            media = raw if raw.startswith("http") else (
                urllib.parse.urlsplit(hanerix).scheme + "://"
                + urllib.parse.urlsplit(hanerix).netloc + raw)
    if not media:
        match = PACKER_FILE_RE.search(config)
        if match:
            media = match.group(1)
    if not media:
        result["status"] = "unknown"
        result["notes"].append("unpacked config carries no hls2 / hls4 / file URL")
        return result
    result["final_url"] = absolutize(media)
    result["sources"] = [{"url": result["final_url"], "mime": "",
                          "label": "hls" if result["final_url"].endswith(".m3u8")
                          else ""}]
    _expires_at, result["expires_in"] = expiry_from_url(result["final_url"])
    result["signed_params"] = sorted(signature_params(result["final_url"]))
    if not verify:
        result["notes"].append("decoded only; the byte endpoint was not probed")
        return result
    probe = _probe_playlist_or_file(result["final_url"], fetch, hanerix)
    result["http_status"] = probe["http_status"]
    result["content_type"] = probe["content_type"]
    result["size_bytes"] = probe["size_bytes"]
    result["status"] = probe["status"]
    if probe["reason"]:
        result["notes"].append(probe["reason"])
    return result


# ---------------------------------------------------------------------------
# uploadflix — generic XFS doFree
# ---------------------------------------------------------------------------

def _xfs_form_fields(body: str) -> dict | None:
    """The hidden fields of the first XFS download form on the page, or None.

    The form's `op` decides the step: download1 (free) or download2 (final).
    Name and value are read separately per input tag because the attribute
    order is the page's choice, not ours.
    """
    attr_re = re.compile(r"""\b(name|value)\s*=\s*["']([^"']*)["']""", re.I)
    for match in UPLOADFLIX_FORM_RE.finditer(body or ""):
        fields = {}
        for tag in re.finditer(r"<input\b[^>]*>", match.group("body"), re.I):
            attrs = dict(attr_re.findall(tag.group(0)))
            if attrs.get("name"):
                fields[attrs["name"]] = attrs.get("value") or ""
        if fields.get("op") in ("download1", "download2") and fields.get("id"):
            return fields
    return None


def _uploadflix_dllink(page: str, page_host: str) -> str:
    """The storage-host dllink anchor out of a file page, or "".

    The anchor lives on a host other than the file host (the storage host),
    path /d/<long token>/<filename>. A video extension wins when several
    anchors are present; otherwise the first match. The href carries spaces
    in the filename, so the whole quoted value is read and quoted before
    any request is made with it.
    """
    candidates = []
    for match in UPLOADFLIX_DLLINK_RE.finditer(page or ""):
        url = match.group("url")
        host = (urllib.parse.urlsplit(url).hostname or "").lower()
        if host and host != page_host:
            candidates.append(url)
    if not candidates:
        return ""
    for url in candidates:
        if urllib.parse.urlsplit(url).path.lower().endswith(UPLOADFLIX_VIDEO_EXTS):
            return urllib.parse.quote(url, safe="/:#?&=@!$'()*+,;%")
    return urllib.parse.quote(candidates[0], safe="/:#?&=@!$'()*+,;%")


def unwrap_uploadflix(url: str, fetch=None, verify: bool = True) -> dict:
    """
    uploadflix file URL -> {final_url, service, is_temporary, expires_in, status, notes, …}.

    Generic XFS doFree (verified live 2026-11-08): GET the file page
    (dl.uploadflix.com/<id> 302s to 1uploadflix.net/f/<id>), read the
    storage-host dllink anchor off the page, one Range probe of it over an
    unverified-SSL fetch (the storage host's certificate is self-signed).
    When the page shows a download form instead of the anchor, the form is
    POSTed the JD way — download1 first (method_free set, method_premium
    dropped), then download2 (adblock_detected=0) — and the anchor is read
    off the answer. No countdown is ever slept: the waits are client-side
    theatre. The dllink token rotates on every page load, so the link is a
    result, never stored durably; the resolver re-unwraps on every press.
    """
    page_fetch = fetch or _cookie_jar_fetch()
    result = _new_result(SERVICE_UPLOADFLIX, url)
    page_url = result["embed_url"]
    status, body, _headers, final_url = page_fetch(page_url)
    if status != 200:
        result["status"] = ("dead" if status in (404, 410)
                            else "blocked" if status in (401, 403, 429)
                            else "unknown")
        result["notes"].append(f"file page HTTP {status}")
        return result
    page = _page_text(body)
    page_url = final_url or page_url
    page_host = (urllib.parse.urlsplit(page_url).hostname or "").lower()
    link = _uploadflix_dllink(page, page_host)
    # The form fallback: a page that shows download1/download2 first.
    for _attempt in range(2):
        if link:
            break
        fields = _xfs_form_fields(page)
        if not fields:
            break
        if fields.get("op") == "download1":
            fields["method_free"] = fields.get("method_free") or "Free Download"
            fields.pop("method_premium", None)
        else:
            fields["adblock_detected"] = "0"
            fields.pop("method_premium", None)
        data = urllib.parse.urlencode(fields).encode()
        status, body, _headers, _final = page_fetch(
            page_url,
            headers={"Content-Type": "application/x-www-form-urlencoded",
                     "Referer": page_url},
            method="POST", data=data)
        if status != 200:
            result["status"] = ("dead" if status in (404, 410)
                                else "blocked" if status in (401, 403, 429)
                                else "unknown")
            result["notes"].append(f"download form HTTP {status}")
            return result
        page = _page_text(body)
        link = _uploadflix_dllink(page, page_host)
    if not link:
        result["status"] = "unknown"
        result["notes"].append("file page carries no storage-host direct link")
        return result
    result["final_url"] = link
    result["sources"] = [{"url": link, "mime": "", "label": ""}]
    if not verify:
        result["notes"].append("unpacked only; the byte endpoint was not probed")
        return result
    # The probe must travel over the unverified context: the storage host's
    # certificate is self-signed, and the verified default would fail the
    # handshake and call a live file dead. An injected fetch (tests) is
    # used as-is — it plays the probe itself.
    probe_fetch = fetch or _unverified_fetch
    probe = probe_range(link, fetch=probe_fetch)
    result["http_status"] = probe["http_status"]
    result["content_type"] = probe["content_type"]
    result["size_bytes"] = probe["size_bytes"]
    result["status"] = probe["status"]
    if probe["reason"]:
        result["notes"].append(probe["reason"])
    return result


# ---------------------------------------------------------------------------
# 1xplayer — playlist POST + CSRF key
# ---------------------------------------------------------------------------

def _m3u8_variants(body: str, base_url: str) -> list[tuple[int, str]]:
    """(resolution height, absolute URL) for each variant in a master playlist."""
    out = []
    for match in XPLAYER_VARIANT_RE.finditer(body or ""):
        out.append((int(match.group(1)),
                    urllib.parse.urljoin(base_url, match.group(2).strip())))
    if not out:
        for line in (body or "").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and line.endswith(".m3u8"):
                out.append((0, urllib.parse.urljoin(base_url, line)))
    return out


def _ts_segment_ok(body, content_type: str) -> bool:
    """Whether a Range slice is real MPEG-TS: video/mp2t, or the 0x47 sync."""
    data = body if isinstance(body, bytes) else (body or "").encode("utf-8", "ignore")
    if (content_type or "").split(";")[0].strip().lower().startswith("video/"):
        return True
    return len(data) >= 189 and data[0:1] == b"\x47" and data[188:189] == b"\x47"


def unwrap_1xplayer(url: str, fetch=None, verify: bool = True) -> dict:
    """
    1xplayer play URL -> {final_url, service, is_temporary, expires_in, status, notes, …}.

    Chain (verified live 2026-11-08): GET the play page (vd.1xplayer.com
    302s to a rotating host), read the per-load `p3.file` (starts `~`) and
    `p3.key` (64 chars) out of the inline player config, POST
    /playlist/<file-minus-~>.txt with X-CSRF-TOKEN = key, which answers
    one signed master URL. The master, its variants and its segments are
    signed to the requesting IP (~2h) AND gated on Referer: the play page
    — a bare master GET 404s, with the Referer it answers 200 #EXTM3U
    with 4 variants — so every request in the chain carries the play page
    as Referer, and the resolver MUST re-resolve per play and NEVER cache
    the master URL. verify=True goes one step further than the master: the
    highest variant playlist is fetched and its first .ts segment
    Range-probed (206 video/mp2t, 0x47 sync) — a master alone proves the
    playlist exists, the segment proves the video does.
    """
    fetch = fetch or http_request
    result = _new_result(SERVICE_1XPLAYER, url)
    status, body, _headers, final_url = fetch(result["embed_url"])
    if status != 200:
        result["status"] = ("dead" if status in (404, 410)
                            else "blocked" if status in (401, 403, 429)
                            else "unknown")
        result["notes"].append(f"play page HTTP {status}")
        return result
    page = _page_text(body)
    play_url = final_url or result["embed_url"]
    file_match = XPLAYER_FILE_RE.search(page)
    key_match = XPLAYER_KEY_RE.search(page)
    if not file_match or not key_match:
        result["status"] = "unknown"
        result["notes"].append("play page carries no p3 file/key config")
        return result
    file_value, key_value = file_match.group(1), key_match.group(1)
    if not file_value.startswith("~") or not 60 <= len(key_value) <= 70:
        result["status"] = "unknown"
        result["notes"].append("p3 file/key are not in the expected shape")
        return result
    host = urllib.parse.urlsplit(play_url).netloc
    playlist_url = f"https://{host}/playlist/{file_value[1:]}.txt"
    status, body, _headers, _final = fetch(
        playlist_url,
        headers={"X-CSRF-TOKEN": key_value,
                 "Content-Type": "application/x-www-form-urlencoded",
                 "Referer": play_url},
        method="POST", data=b"")
    if status != 200:
        result["status"] = ("dead" if status in (404, 410)
                            else "blocked" if status in (401, 403, 429)
                            else "unknown")
        result["notes"].append(f"playlist POST HTTP {status}")
        return result
    master = _page_text(body).strip()
    if not master.startswith("http") or ".m3u8" not in master.split("?")[0]:
        result["status"] = "unknown"
        result["notes"].append("playlist answer is not a master URL")
        return result
    result["final_url"] = master
    result["sources"] = [{"url": master, "mime": "application/vnd.apple.mpegurl",
                          "label": "hls"}]
    expiry = XPLAYER_MASTER_EXPIRY_RE.search(master)
    if expiry:
        result["expires_in"] = max(0, int(expiry.group(1)) - int(time.time()))
    if not verify:
        result["notes"].append("playlist only; the byte endpoint was not probed")
        return result
    # The master is Referer-gated: a bare GET 404s, with the play page as
    # Referer it answers 200 #EXTM3U. The same Referer rides the variant
    # and the segment below.
    status, body, headers, _final = fetch(
        master, headers={"Referer": play_url}, method="GET")
    if status != 200:
        result["status"] = ("dead" if status in (404, 410)
                            else "blocked" if status in (401, 403, 429)
                            else "unknown")
        result["notes"].append(f"master playlist HTTP {status}")
        return result
    master_body = _page_text(body)
    if not master_body.startswith("#EXTM3U"):
        result["status"] = "unknown"
        result["notes"].append("master answer is not a playlist")
        return result
    result["http_status"] = status
    result["content_type"] = (headers.get("content-type") or "").split(";")[0].strip().lower()
    result["size_bytes"] = len(body) if isinstance(body, bytes) else None
    variants = _m3u8_variants(master_body, master)
    if not variants:
        result["status"] = "unknown"
        result["notes"].append("master playlist names no variant")
        return result
    _height, variant_url = max(variants, key=lambda item: item[0])
    status, body, _headers, _final = fetch(
        variant_url, headers={"Referer": play_url}, method="GET")
    if status != 200:
        result["status"] = ("dead" if status in (404, 410)
                            else "blocked" if status in (401, 403, 429)
                            else "unknown")
        result["notes"].append(f"variant playlist HTTP {status}")
        return result
    segment_url = ""
    for match in XPLAYER_SEGMENT_RE.finditer(_page_text(body)):
        segment_url = urllib.parse.urljoin(variant_url, match.group(1))
        break
    if not segment_url:
        result["status"] = "unknown"
        result["notes"].append("variant playlist names no segment")
        return result
    status, body, headers, _final = fetch(
        segment_url,
        headers={"Range": f"bytes=0-{RANGE_PROBE_BYTES - 1}",
                 "Referer": play_url},
        method="GET")
    content_type = (headers.get("content-type") or "").split(";")[0].strip().lower()
    if status == 206 and _ts_segment_ok(body, content_type):
        result["status"] = "active"
        return result
    result["status"] = ("dead" if status in (404, 410)
                        else "blocked" if status in (401, 403, 429)
                        else "unknown")
    result["notes"].append(
        f"segment probe HTTP {status} {content_type or 'no content-type'}")
    return result


# ---------------------------------------------------------------------------
# MovieBox — signed play API (themoviebox.xyz + 123moviesfree.club)
# ---------------------------------------------------------------------------

def _moviebox_pick_stream(streams) -> dict | None:
    """The best free MP4 stream: highest resolution, vipLocked false, URL present."""
    best = None
    for item in streams or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("format") or "").upper() != "MP4":
            continue
        if item.get("vipLocked"):
            continue
        url = str(item.get("url") or "").strip()
        if not url.lower().startswith("https:"):
            continue
        try:
            resolution = int(str(item.get("resolutions") or "0"))
        except ValueError:
            resolution = 0
        if best is None or resolution > best[0]:
            best = (resolution, item)
    return best[1] if best else None


def unwrap_moviebox(url: str, fetch=None, verify: bool = True) -> dict:
    """
    MovieBox detail URL -> {final_url, service, is_temporary, expires_in, status, notes, …}.

    Chain (verified live 2026-11-08 on both skins): the stored detail URL
    gives the slug; GET the detail API for the numeric subjectId (and the
    seasons, for series); GET the play API with Referer = the /movies/
    player-page URL — that Referer is the whole discriminator (the same
    call from /detail/ returns streams:[], and no cookies are needed at
    all) — and pick the highest free MP4 stream (vipLocked:false, non-empty
    URL). DASH is vipLocked and needs an Edge-Cache-Cookie + X-MB-Token,
    so it is never taken. The signed MP4 URL is probed with GET Range
    only — never HEAD, which the CDN answers 429 — with the player page
    as Referer, and re-resolved on every press: sign+t are stable per
    resource short-term, but the resolver never serves a stored one.
    """
    fetch = fetch or http_request
    result = _new_result(SERVICE_MOVIEBOX, url)
    parsed = urllib.parse.urlsplit(result["embed_url"])
    base = f"{parsed.scheme}://{parsed.netloc}"
    host = (parsed.hostname or "").lower()
    if not MOVIEBOX_HOST_RE.search(host):
        result["status"] = "unknown"
        result["notes"].append("not a MovieBox detail URL")
        return result
    detail = MOVIEBOX_DETAIL_RE.search(parsed.path or "")
    if not detail:
        result["status"] = "unknown"
        result["notes"].append("MovieBox URL carries no detail slug")
        return result
    slug = detail.group(1)
    query = urllib.parse.parse_qs(parsed.query or "")
    season = (query.get("se") or query.get("detailSe") or ["0"])[0]
    episode = (query.get("ep") or query.get("detailEp") or ["0"])[0]
    status, body, _headers, _final = fetch(
        f"{base}/wefeed-h5api-bff/detail?detailPath={urllib.parse.quote(slug)}")
    if status != 200:
        result["status"] = ("dead" if status in (404, 410)
                            else "blocked" if status in (401, 403, 429)
                            else "unknown")
        result["notes"].append(f"detail API HTTP {status}")
        return result
    try:
        detail_json = json.loads(_page_text(body))
        subject = (detail_json.get("data") or {}).get("subject") or {}
        subject_id = subject.get("subjectId")
    except Exception:  # noqa: BLE001 - a bad detail answer must not crash
        subject_id = None
    if not subject_id:
        result["status"] = "unknown"
        result["notes"].append("detail API carries no subjectId")
        return result
    referer = (f"{base}/movies/{slug}?id={subject_id}"
               "&type=/movie/detail&detailSe=&detailEp=&lang=en")
    play_url = (f"{base}/wefeed-h5api-bff/subject/play"
                f"?subjectId={subject_id}&se={season}&ep={episode}"
                f"&detailPath={urllib.parse.quote(slug)}")
    status, body, _headers, _final = fetch(
        play_url, headers={"Referer": referer})
    if status != 200:
        result["status"] = ("dead" if status in (404, 410)
                            else "blocked" if status in (401, 403, 429)
                            else "unknown")
        result["notes"].append(f"play API HTTP {status}")
        return result
    try:
        play_json = json.loads(_page_text(body))
        streams = (play_json.get("data") or {}).get("streams")
    except Exception:  # noqa: BLE001 - a bad play answer must not crash
        streams = None
    if streams is None:
        result["status"] = "unknown"
        result["notes"].append("play API answer is not JSON")
        return result
    picked = _moviebox_pick_stream(streams)
    if picked is None:
        result["status"] = "unknown"
        result["notes"].append("play API offers no free MP4 stream")
        return result
    result["final_url"] = str(picked["url"])
    result["sources"] = [
        {"url": str(item.get("url") or ""), "mime": "video/mp4",
         "label": f"{item.get('resolutions')}p"}
        for item in streams
        if isinstance(item, dict)
        and str(item.get("format") or "").upper() == "MP4"
        and not item.get("vipLocked")
        and str(item.get("url") or "").startswith("https:")]
    try:
        result["size_bytes"] = int(str(picked.get("size") or "0")) or None
    except ValueError:
        result["size_bytes"] = None
    if not verify:
        result["notes"].append("play API only; the byte endpoint was not probed")
        return result
    # GET Range only, with the player page as Referer — the CDN answers 429
    # to HEAD, and the replay that proved the URL carried the same Referer.
    probe = _probe_playlist_or_file(result["final_url"], fetch, referer)
    result["http_status"] = probe["http_status"]
    result["content_type"] = probe["content_type"]
    if probe["size_bytes"] is not None:
        result["size_bytes"] = probe["size_bytes"]
    result["status"] = probe["status"]
    if probe["reason"]:
        result["notes"].append(probe["reason"])
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
