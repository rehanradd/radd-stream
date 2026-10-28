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
"""

from __future__ import annotations

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
# mistaken for this one.
MXDROP_HOST_RE = re.compile(r"(?:^|\.)mxdrop\.(?:to|top)$", re.I)
MXDROP_CONTENT_RE = re.compile(r"^/(?:e|embed)/[A-Za-z0-9_-]+/?$", re.I)

# pkembed's own page: `https://pkembed.site/embed-<filecode>.html`. The shape is
# `/embed-<code>.html`, NOT mxdrop's `/e/<id>` — a matcher that requires `/e/`
# finds zero pkembeds. `pkembed.online` is a sibling this catalog publishes
# rarely and has not been re-verified here, so it is recognized but stays
# honest: an unpack that fails on it reports `unknown`, never `active`.
PKEMBED_HOST_RE = re.compile(r"(?:^|\.)pkembed\.(?:site|online)$", re.I)
PKEMBED_CONTENT_RE = re.compile(r"^/embed-[A-Za-z0-9]+\.html$", re.I)

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

SERVICE_MXDROP = "mxdrop"
SERVICE_PKEMBED = "pkembed"


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
                 method: str = "GET", follow: bool = True):
    """
    (status, body, headers, final_url) for one request.

    A redirect that was asked not to be followed comes back as its 3xx with the
    Location in `headers`; a transport failure comes back as status 0 with the
    reason in the body, because a resolver's job is to name what it saw.
    """
    fields = {"User-Agent": USER_AGENT}
    fields.update(headers or {})
    request = urllib.request.Request(url, headers=fields, method=method)
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


def probe_range(url: str, size: int = RANGE_PROBE_BYTES,
                fetch=http_request) -> dict:
    """
    Ask the byte endpoint for the first `size` bytes and report what came back.

    206 + video/* is the answer that matters: the file exists and the signature
    is live. A plain 200 is recorded as `active` too but flagged `full_body`,
    because a host that ignores Range is telling us something a client should
    know before it plans a seek.
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
    if status == 0:
        verdict["status"] = "error"
        verdict["reason"] = str(body)[:200]
    elif status == 206:
        verdict["status"] = "active" if content_type.startswith("video/") else "unknown"
        verdict["reason"] = "" if content_type.startswith("video/") else f"206 {content_type}"
    elif status == 200:
        verdict["status"] = "active" if content_type.startswith("video/") else "blocked"
        verdict["reason"] = "full_body" if content_type.startswith("video/") else f"200 {content_type}"
        if verdict["status"] == "active" and total is None:
            verdict["size_bytes"] = len(body) if isinstance(body, (bytes, str)) else None
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


def main(argv: list[str] | None = None) -> int:
    """One URL in, one JSON verdict out — a manual check of the chain."""
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print(__doc__.strip().splitlines()[0])
        print("usage: host_resolvers.py <embed-url> [--no-verify]")
        return 2
    url = args[0]
    unwrap = unwrap_pkembed if is_pkembed_embed(url) else unwrap_mxdrop
    verdict = unwrap(url, verify="--no-verify" not in args)
    print(json.dumps(verdict, indent=2, ensure_ascii=False))
    return 0 if verdict["status"] in ("active", "unverified") else 1


if __name__ == "__main__":
    sys.exit(main())
