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
and a ticket (`_t`). Replaying a stored signature returns 403 while the host's
own poster still returns 200, which is how `unwrap_mxdrop` tells "this
signature expired" from "this host is gone". The consequence for callers is
explicit: **the embed URL is the durable identifier; the mp4 URL is a result of
this call and must not be persisted.** `unwrap_mxdrop` therefore returns it to
the caller and leaves it out of every stored shape.
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

# eval(function(p,a,c,k,e,d){…}('<payload>',10,27,'k1|k2|…'.split('|'),0,{}))
PACKER_RE = re.compile(
    r"""eval\(\s*function\s*\(\s*p\s*,\s*a\s*,\s*c\s*,\s*k\s*,\s*e\s*,\s*d\s*\)"""
    r"""\s*\{.*?\}\s*\(\s*'(.*?)'\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*'(.*?)'"""
    r"""\s*\.split\(\s*'\|'\s*\)\s*,\s*(\d+)\s*,\s*\{\}\s*\)\s*\)""",
    re.S,
)
MD_FIELD_RE = re.compile(r'MDCore\.(\w+)\s*=\s*"([^"]*)"')
MD_ARRAY_RE = re.compile(r"MDCore\.(\w+)\s*=\s*(\[(?:[^\[\]]|\[[^\[\]]*\])*\])")
SIGNED_QUERY_KEYS = frozenset({"s", "sig", "signature", "token", "auth_key", "_t",
                               "e", "expires", "exp"})

# Referrers that are known to make these hosts answer 403. Never sent, checked
# in code so a future caller cannot reintroduce the bug.
FORBIDDEN_REFERRERS = ("moviesmela", "hindidubbedmovies", "moviehax")

SERVICE_MXDROP = "mxdrop"


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
    `if(k[c])` test.
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
    return unpack_packed_js(payload, radix, count, keylist)


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
    """(expires_at epoch seconds, seconds-from-now) read from the signed query."""
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(url or "").query)
    raw = (query.get("e") or query.get("expires") or query.get("exp") or [""])[0]
    if not re.fullmatch(r"\d{9,11}", raw or ""):
        return None, None
    expires_at = int(raw)
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
# mxdrop
# ---------------------------------------------------------------------------

def is_mxdrop_embed(url: str) -> bool:
    host = (urllib.parse.urlsplit(absolutize(url)).netloc or "").lower()
    if not host:
        return False
    if not MXDROP_HOST_RE.search(host):
        return False
    return bool(MXDROP_CONTENT_RE.match(urllib.parse.urlsplit(absolutize(url)).path or "/"))


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
    result = {"service": SERVICE_MXDROP, "embed_url": absolutize(embed_url),
              "final_url": "", "is_temporary": True, "expires_in": None,
              "status": "unverified", "notes": [], "poster_url": "",
              "signed_params": [], "vfile": "", "vserver": "", "subtitles": []}
    if referer and any(token in referer.lower() for token in FORBIDDEN_REFERRERS):
        referer = None
        result["notes"].append("referrer withheld: this host 403s on the catalog site's referer")
    if not is_mxdrop_embed(result["embed_url"]):
        result["status"] = "unknown"
        result["notes"].append("not an mxdrop embed URL")
        return result

    status, body, _headers, _final = fetch(result["embed_url"])
    if status != 200:
        result["status"] = "dead" if status in (404, 410) else (
            "blocked" if status in (401, 403, 429) else "unknown")
        result["notes"].append(f"embed page HTTP {status}")
        return result

    page = body if isinstance(body, str) else (body or b"").decode("utf-8", "replace")
    config = find_packed_config(page)
    if not config:
        result["status"] = "unknown"
        result["notes"].append("embed page carries no recognisable packed config")
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

    _expires_at, result["expires_in"] = expiry_from_url(wurl)
    result["signed_params"] = sorted(signature_params(wurl))
    if result["expires_in"] is None:
        result["notes"].append("signed query carries no parsable expiry")
    if not verify:
        result["notes"].append("unpacked only; the byte endpoint was not probed")
        return result

    probe = probe_range(wurl, fetch=fetch)
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


def main(argv: list[str] | None = None) -> int:
    """One URL in, one JSON verdict out — a manual check of the chain."""
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print(__doc__.strip().splitlines()[0])
        print("usage: host_resolvers.py <embed-url> [--no-verify]")
        return 2
    verdict = unwrap_mxdrop(args[0], verify="--no-verify" not in args)
    print(json.dumps(verdict, indent=2, ensure_ascii=False))
    return 0 if verdict["status"] in ("active", "unverified") else 1


if __name__ == "__main__":
    sys.exit(main())
