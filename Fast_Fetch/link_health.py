#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
link_health.py — stdlib-only link prober + scorer for ``download_sources``.

Why this exists
---------------
``fast_fetch.probe_single_source()`` / ``run_health_check()`` are database-
coupled: they read a ``download_sources`` row, guess ``status`` and return a
dict. This module is the measurement layer *underneath* that idea: it takes a
bare URL and reports what the endpoint actually does — can the Android client
play it, can it resume a download, how fast, how fresh — so the API can rank
links by real playability instead of by whatever the scraper assumed.

Public surface
--------------
    ProbeResult            frozen dataclass, one measurement
    probe()                measure a single URL (never raises for network facts)
    score_link()           map a ProbeResult to an integer 0..1000 rank
    summarize()            aggregate a batch of results for ops dashboards
    merge_health_history() EWMA blend of historical + newest probe
    probe_many()           ordered ThreadPoolExecutor batch probe

Error codes (``ProbeResult.error`` — stable strings, safe to GROUP BY)
----------------------------------------------------------------------
    ""                success
    "timeout"         socket / read timeout, or server exceeded the budget
    "dns"             hostname does not resolve
    "tls"             TLS handshake failed
    "conn_reset"      peer reset / closed the connection mid-request
    "conn_error"      any other transport failure
    "http_404"...     any 4xx/5xx, suffixed with the status code
    "empty_body"      2xx with zero bytes of payload
    "not_media"       2xx body that is neither playable media nor HTML
    "redirect_loop"   a redirect cycle was detected
    "redirect_limit"  more than ``max_redirects`` hops
    "blocked_target"  refused by the SSRF / hygiene guard (see below)
    "invalid_url"     URL could not even be parsed
    "head_unsupported"  allow_download=False and the server refused HEAD
    "blocklisted"     skipped because the target matched ``url_blocklist``
    "conn_error:<X>"  only from probe_many(): an unexpected bug (class <X>) in
                      one worker, captured so a batch never explodes

Exception policy
----------------
Every socket gets an explicit timeout and every transport failure is folded
into an ``ok=False`` ``ProbeResult``. ``probe()`` therefore never raises for
network reality. The only things that raise are genuine programming errors:
a non-``str`` ``url`` raises ``TypeError`` and a non-numeric ``timeout`` /
``sample_bytes`` raises whatever the interpreter raises.

SSRF / HYGIENE GUARD — READ THIS BEFORE DEPLOYING
-------------------------------------------------
Production probing must **never** touch internal addresses. By default
``probe()`` refuses (``ok=False, error="blocked_target"``):

  * any scheme other than ``http`` / ``https`` (``file``, ``gopher``, ...)
  * URLs with embedded credentials (``https://user:pass@host/...``)
  * ``localhost`` / ``*.localhost`` and every literal address in
    ``127.0.0.0/8``, ``10.0.0.0/8``, ``172.16.0.0/12``, ``192.168.0.0/16``,
    ``169.254.0.0/16`` (covers the ``169.254.169.254`` cloud metadata
    endpoint), ``::1``, ``fe80::/10``, ``fc00::/7``, and the unspecified
    addresses ``0.0.0.0`` / ``::``
  * hostnames that *resolve* into any of those ranges (DNS rebinding)

The guard can only be disabled with the explicit keyword
``allow_private=True``. That flag exists so the offline test suite can probe a
local ``http.server`` it spawns itself. Keep it False everywhere else: nothing
in the scraper, the API, or the heal CLI should ever pass True.
"""

from __future__ import annotations

import concurrent.futures
import http.client
import ipaddress
import os
import re
import socket
import ssl
import time
import urllib.parse
from dataclasses import dataclass

# Same browser UA as config.HTTP_USER_AGENT / fast_fetch.USER_AGENT, written out
# instead of imported on purpose: importing config would compute (and possibly
# create) DB_PATH while live crawlers are writing to it. This module must stay
# importable with zero filesystem side effects. Override with RADD_USER_AGENT.
USER_AGENT = os.environ.get("RADD_USER_AGENT") or (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

__all__ = [
    "ProbeResult",
    "probe",
    "score_link",
    "summarize",
    "merge_health_history",
    "probe_many",
]

# Same posture as fast_fetch.SSL_CONTEXT (public CDNs ship broken chains) and
# the same tradeoff: certificate / hostname verification is OFF, so a probed
# endpoint's identity is not authenticated and a network MITM could pose as the
# CDN. That is acceptable here because probes only ever fetch public media
# bytes and the result feeds a ranking score — never credentials, never a
# trusted identity. Set RADD_LINK_HEALTH_VERIFY_TLS=1 to turn verification on.
if os.environ.get("RADD_LINK_HEALTH_VERIFY_TLS") == "1":
    SSL_CONTEXT = ssl.create_default_context()
else:
    # mirrors fast_fetch.SSL_CONTEXT, written out instead of imported so this
    # module stays loadable without the 4k-line engine
    SSL_CONTEXT = ssl.create_default_context()
    SSL_CONTEXT.check_hostname = False
    SSL_CONTEXT.verify_mode = ssl.CERT_NONE

DEFAULT_TIMEOUT = 8.0
DEFAULT_SAMPLE_BYTES = 524288  # 512 KiB bounded body sample
DEFAULT_MAX_REDIRECTS = 5
MIN_SAMPLE_FOR_SPEED = 4096  # below this the speed number is a fantasy

STREAMABLE_PROTOCOLS = ("hls", "dash", "progressive")

_HLS_CT = ("application/vnd.apple.mpegurl", "application/x-mpegurl",
           "audio/mpegurl", "application/mpegurl")
_DASH_CT = ("application/dash+xml",)
_PROGRESSIVE_CT = (
    "video/mp4", "video/x-matroska", "video/webm", "video/quicktime",
    "video/x-m4v", "video/mpeg", "video/mp2t", "video/3gpp", "video/ogg",
    "audio/mpeg", "audio/mp4", "audio/ogg", "audio/aac",
)
_HTML_CT = ("text/html", "application/xhtml+xml")
_TEXT_CT = ("text/plain", "text/xml", "application/xml", "application/json")

_HLS_EXT = (".m3u8", ".m3u")
_DASH_EXT = (".mpd",)
_PROGRESSIVE_EXT = (".mp4", ".m4v", ".mkv", ".webm", ".ts", ".m2ts", ".mov",
                    ".avi", ".flv", ".3gp", ".ogv", ".mp3", ".m4a", ".aac")

_EMBED_HINT = re.compile(
    r"(<iframe\b|<video[^>]*\ssrc\s*=|jwplayer|hls\.loadSource|video\.src\s*=|"
    r"clipland|player\?src=|data-iframe)", re.IGNORECASE)
_HTML_HINT = re.compile(r"(<html\b|<!doctype\s+html)", re.IGNORECASE)


# ── Result Type ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ProbeResult:
    """One measured truth about one source URL."""

    url: str
    ok: bool = False
    http_status: int = 0
    protocol: str = "unusable"          # hls|dash|progressive|embed|html_page|unusable
    content_type: str = ""              # normalized, no parameters
    size_bytes: int = 0                 # 0 when unknown
    accepts_ranges: bool = False
    resumable: bool = False
    cors_open: bool = False
    latency_ms: int = 0                 # monotonic, headers of the final response
    download_speed_mbps: float = 0.0    # bounded sample, 0.0 when not measurable
    streamable: bool = False
    downloadable: bool = False
    redirects_to: str = ""              # final URL after redirects, "" if none
    error: str = ""                     # "" or a stable short code
    checked_at: float = 0.0             # unix timestamp


# ── SSRF / hygiene guard ─────────────────────────────────────────────────────

def _blocked_host_reason(host: str) -> str:
    """Return a reason string when *host* is off-limits, else ``""``."""
    h = (host or "").strip().lower().rstrip(".")
    if not h:
        return "empty host"
    if h == "localhost" or h.endswith(".localhost"):
        return "localhost"
    literal = h
    if literal.startswith("[") and literal.endswith("]"):  # IPv6 URL form
        literal = literal[1:-1]
    try:
        addr = ipaddress.ip_address(literal)
    except ValueError:
        addr = None
    if addr is not None:
        if addr.is_private or addr.is_loopback or addr.is_link_local or \
                addr.is_multicast or addr.is_reserved or addr.is_unspecified:
            return f"private address {addr}"
        return ""
    # Not a literal: resolve it, because a public-looking name may point inside.
    try:
        infos = socket.getaddrinfo(h, None, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError, OSError):
        return ""  # unresolvable — the connect attempt will report "dns"
    for info in infos:
        try:
            addr = ipaddress.ip_address(info[4][0])
        except (ValueError, IndexError):
            continue
        if addr.is_loopback or addr.is_private or addr.is_link_local or \
                addr.is_multicast or addr.is_reserved or addr.is_unspecified:
            return f"{h} resolves to private address {addr}"
    return ""


def _block_reason(url: str, allow_private: bool) -> str:
    """Why this URL must not be probed; ``""`` means allowed.

    Returns the sentinel ``"invalid_url"`` for a URL that cannot even be
    parsed, so :func:`probe` can report it as its own stable error code.
    """
    try:
        parts = urllib.parse.urlsplit(url)
        port = parts.port  # raises ValueError for garbage ports
    except ValueError:
        return "invalid_url"
    if parts.scheme.lower() not in ("http", "https"):
        return f"unsupported scheme {parts.scheme!r}"
    if "@" in (parts.netloc or ""):
        return "embedded credentials"
    if not parts.hostname:
        return "missing host"
    if allow_private:
        return ""
    return _blocked_host_reason(parts.hostname)


# ── low level HTTP (http.client, so redirects/ranges stay under our control) ─

class _Exchange:
    """Raw outcome of one request. ``error`` is a stable code, never an exception."""

    __slots__ = ("status", "headers", "body", "error", "header_ms", "body_ms",
                 "location")

    def __init__(self, status=0, headers=None, body=b"", error="",
                 header_ms=0, body_ms=0):
        self.status = status
        self.headers = headers or {}
        self.body = body
        self.error = error
        self.header_ms = header_ms          # connect+send+headers, this hop
        self.body_ms = body_ms              # bounded body read, this hop
        self.location = ""


def _header_get(headers: dict, name: str) -> str:
    return headers.get(name.lower(), "") if headers else ""


def _request_target(parts) -> str:
    target = parts.path or "/"
    if parts.query:
        target += "?" + parts.query
    return target


def _raw_request(url: str, method: str, headers: dict, timeout: float,
                 sample_bytes: int) -> _Exchange:
    """Perform exactly one request/response, never following redirects."""
    parts = urllib.parse.urlsplit(url)
    host = parts.hostname or ""
    port = parts.port or (443 if parts.scheme == "https" else 80)
    conn = None
    t0 = time.monotonic()
    try:
        if parts.scheme == "https":
            conn = http.client.HTTPSConnection(host, port, timeout=timeout,
                                               context=SSL_CONTEXT)
        else:
            conn = http.client.HTTPConnection(host, port, timeout=timeout)
        conn.request(method, _request_target(parts), headers=headers)
        resp = conn.getresponse()
        header_ms = int((time.monotonic() - t0) * 1000)
        raw_headers = [(k.lower(), v) for k, v in resp.getheaders()]
        exch = _Exchange(status=resp.status, headers=dict(raw_headers),
                         error="", header_ms=header_ms)
        exch.location = _header_get(exch.headers, "location")
        if method != "HEAD":
            tb = time.monotonic()
            try:
                exch.body = resp.read(sample_bytes) if sample_bytes > 0 else b""
            except (socket.timeout, TimeoutError):
                exch.error = "timeout"
            exch.body_ms = int((time.monotonic() - tb) * 1000)
        return exch
    except (socket.timeout, TimeoutError):
        return _Exchange(error="timeout",
                         header_ms=int((time.monotonic() - t0) * 1000))
    except socket.gaierror:
        return _Exchange(error="dns")
    except ssl.SSLError:
        return _Exchange(error="tls")
    except (http.client.BadStatusLine, http.client.RemoteDisconnected,
            ConnectionResetError, BrokenPipeError):
        return _Exchange(error="conn_reset")
    except (http.client.HTTPException, OSError) as exc:
        # InvalidURL / UnknownProtocol / refused connection / TLS wrap errors
        code = "tls" if "ssl" in str(exc).lower() else "conn_error"
        return _Exchange(error=code)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _chain(url: str, method: str, headers: dict, timeout: float,
           sample_bytes: int, max_redirects: int):
    """Follow redirects manually so cycles and hop counts are observable.

    Returns ``(exchange, final_url, error)``. ``exchange`` is ``None`` when the
    chain died on transport errors before any response.
    """
    current = url
    seen = {current}
    for hop in range(max_redirects + 1):
        exch = _raw_request(current, method, headers, timeout, sample_bytes)
        if exch.error:
            return exch, current, exch.error
        if 300 <= exch.status < 400:
            loc = exch.location
            if not loc:
                return exch, current, ""
            nxt = urllib.parse.urljoin(current, loc)
            if nxt in seen:
                return exch, nxt, "redirect_loop"
            if hop == max_redirects:
                return exch, nxt, "redirect_limit"
            seen.add(nxt)
            current = nxt
            continue
        return exch, current, ""
    return None, current, "redirect_limit"  # pragma: no cover - loop guard


# ── classification ───────────────────────────────────────────────────────────

def _normalize_content_type(content_type: str) -> str:
    return (content_type or "").split(";")[0].strip().lower()


def _extension(path: str) -> str:
    tail = path.rstrip("/").split("/")[-1].lower()
    idx = tail.rfind(".")
    if idx == -1 or len(tail) - idx > 7:
        return ""
    ext = tail[idx:]
    return ext if re.fullmatch(r"\.[a-z0-9]+", ext) else ""


def _looks_binary_media(body: bytes) -> bool:
    if len(body) < 12:
        return False
    if body[4:8] in (b"ftyp", b"moov", b"mdat"):
        return True                        # ISO base media (mp4/m4v/mov)
    if body[:4] == b"\x1a\x45\xdf\xa3":
        return True                        # EBML — matroska / webm
    if body[:3] == b"ID3" or body[:2] == b"\xff\xfb" or body[:2] == b"\xff\xf3":
        return True                        # mp3 frames
    if body[0] == 0x47 and (len(body) < 189 or body[188] == 0x47):
        return True                        # MPEG-TS packet
    return False


def _body_text(body: bytes) -> str:
    try:
        return body[:65536].decode("utf-8", errors="ignore")
    except Exception:  # pragma: no cover - decode guard
        return ""


def _sniff(body: bytes) -> str:
    """Protocol from the first bytes; '' when the body says nothing."""
    if not body:
        return ""
    head = body[:64].lstrip()
    if head.startswith(b"#EXTM3U"):
        return "hls"                       # manifest without a hint in headers
    if head[:5].lower() in (b"<?xml",) and b"MPEG-DASH" in body[:2048]:
        return "dash"
    if _looks_binary_media(body):
        return "progressive"
    if body[:1] == b"{" or body[:1] == b"[":
        return "unusable"
    text = _body_text(body)
    if _EMBED_HINT.search(text):
        return "embed"
    if _HTML_HINT.search(text) or text.lstrip()[:1] == "<":
        return "html_page"
    return ""


def _classify(ext: str, content_type: str, body: bytes) -> str:
    """Protocol for a live 2xx response. Never returns ''."""
    if ext in _HLS_EXT:
        return "hls"
    if ext in _DASH_EXT:
        return "dash"
    if ext in _PROGRESSIVE_EXT:
        return "progressive"
    if content_type in _HLS_CT:
        return "hls"
    if content_type in _DASH_CT:
        return "dash"
    if content_type in _PROGRESSIVE_CT or content_type.startswith(("video/", "audio/")):
        return "progressive"
    sniffed = _sniff(body)
    if sniffed:
        return sniffed
    if content_type in _HTML_CT:
        return "html_page"
    if content_type in _TEXT_CT:
        return "unusable"
    return "unusable"


def _total_size(exch: _Exchange) -> int:
    """Declared byte size of the whole resource (0 = unknown).

    Header-driven only: a ranged reply's ``Content-Length`` is the slice and a
    chunked body has no declared total, so we never infer a file size from the
    bytes we happened to sample.
    """
    crange = _header_get(exch.headers, "content-range")
    if crange and "/" in crange:
        total = crange.rsplit("/", 1)[-1].strip()
        if total.isdigit() and int(total) > 0:
            return int(total)
    if exch.status == 206:
        return 0  # 206 without Content-Range says nothing about the whole file
    clen = _header_get(exch.headers, "content-length")
    if clen and clen.isdigit():
        return int(clen)
    return 0


def _hls_has_media(body: bytes) -> bool:
    """True when an HLS manifest points at at least one resolvable media URI."""
    text = _body_text(body)
    if "#EXT-X-STREAM-INF" in text or "#EXTINF" in text:
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.lower().endswith((".m3u8", ".ts", ".mp4", ".aax", ".m4s")) \
                    or "://" in line or line.startswith("/"):
                return True
    return False


# ── the probe ────────────────────────────────────────────────────────────────

def probe(url: str, *, final_url: str = "", timeout: float = DEFAULT_TIMEOUT,
          sample_bytes: int = DEFAULT_SAMPLE_BYTES, headers: dict | None = None,
          allow_download: bool = True, allow_private: bool = False,
          max_redirects: int = DEFAULT_MAX_REDIRECTS,
          service: str = "") -> ProbeResult:
    """Measure *url* and return a :class:`ProbeResult`.

    Args:
        url: the stored ``source_url`` (or ``final_url``) to knock on.
        final_url: the resolver's expected landing URL. Used two ways: as a
            classification hint (its file extension stands in when the tokenized
            ``url`` has none) and as the reference for redirect drift — when the
            probe lands on a *different host*, the link still reports
            ``ok=True`` and the landing URL is exposed in ``redirects_to`` so ops
            can re-canon it.
        timeout: per-socket budget in seconds (connect, headers, each read).
        sample_bytes: hard cap on body bytes ever downloaded (default 512 KiB).
        headers: extra request headers (User-Agent / Referer per service).
        allow_download: False disables the bounded GET, so no speed or body
            sniffing is possible — protocol comes from headers only.
        allow_private: ONLY for tests that probe a local server. See the module
            docstring: production probing must never set this.
        max_redirects: hop budget before ``redirect_limit``; cycles are
            detected independently and report ``redirect_loop``.
        service: informational (``hubcloud``, ``fastdl``, ...); reserved for
            per-service header presets, currently unused.

    Raises:
        TypeError: only when *url* is not a ``str`` — a programming error, not
            a network fact. Every transport failure becomes ``ok=False``.
    """
    if not isinstance(url, str):
        raise TypeError(f"probe() needs a str url, got {type(url).__name__}")
    now = time.time()

    blocked = _block_reason(url, allow_private)
    if blocked:
        code = blocked if blocked == "invalid_url" else "blocked_target"
        return ProbeResult(url=url, ok=False, http_status=0,
                           protocol="unusable", error=code, checked_at=now)

    parts = urllib.parse.urlsplit(url)
    origin = f"{parts.scheme.lower()}://{parts.netloc.lower()}"
    req_headers = {
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "close",
        "Origin": origin,
    }
    if headers:
        for k, v in dict(headers).items():
            if isinstance(k, str):
                req_headers[k] = str(v)

    # The resolver's expected landing URL often carries the file extension that
    # the tokenized source_url lacks (e.g. .../genxfm/<token> -> .../movie.mp4),
    # so it is a legitimate classification hint.
    hint_ext = _extension(urllib.parse.urlsplit(final_url).path) if final_url else ""

    # ── phase 1: HEAD (cheap), fall through to GET when unsupported
    head, head_final, head_err = _chain(url, "HEAD", req_headers, timeout,
                                        0, max_redirects)
    latency_ms = head.header_ms if head is not None else 0
    # need_get: HEAD answered nothing useful (405 / 400 / 501 / no HEAD at all)
    need_get = True
    if head is not None and not head_err and head.status not in (400, 405, 501):
        if head.status >= 400:
            return _finalize(url, head, head_final, b"",
                             error=_status_error(head.status),
                             latency_ms=latency_ms, now=now, origin=origin,
                             redirects_to=head_final)
        need_get = False
    elif head_err:
        # timeout / dns / tls / reset / redirect cycle: a GET only burns the
        # same budget again, so report the transport truth.
        return ProbeResult(url=url, ok=False,
                           http_status=head.status if head else 0,
                           protocol="unusable",
                           redirects_to=head_final if head_final != url else "",
                           latency_ms=latency_ms, error=head_err, checked_at=now)

    if not allow_download:
        if need_get:
            return ProbeResult(url=url, ok=False, http_status=head.status,
                               protocol="unusable", latency_ms=latency_ms,
                               error="head_unsupported", checked_at=now)
        # HEAD-only mode: no body evidence, so protocol comes from headers +
        # extension, and speed is unmeasurable by definition.
        return _finalize(url, head, head_final, b"", error="", latency_ms=latency_ms,
                         now=now, origin=origin, redirects_to=head_final,
                         head=head, head_only=True, hint_ext=hint_ext)

    # ── phase 2: bounded GET with a Range probe
    get_headers = dict(req_headers)
    get_headers["Range"] = f"bytes=0-{max(int(sample_bytes) - 1, 0)}"
    exch, chain_final, chain_err = _chain(url, "GET", get_headers, timeout,
                                          sample_bytes, max_redirects)
    if exch is None:
        return ProbeResult(url=url, ok=False, http_status=0, protocol="unusable",
                           latency_ms=latency_ms, error=chain_err or "conn_error",
                           redirects_to=chain_final if chain_final != url else "",
                           checked_at=now)
    latency_ms = max(latency_ms, exch.header_ms)
    landed = chain_final if chain_final != url else ""
    if chain_err in ("redirect_loop", "redirect_limit"):
        return ProbeResult(url=url, ok=False, http_status=exch.status,
                           protocol="unusable", latency_ms=latency_ms,
                           redirects_to=landed, error=chain_err, checked_at=now)
    if exch.error:
        return ProbeResult(url=url, ok=False, http_status=exch.status,
                           protocol="unusable", latency_ms=latency_ms,
                           redirects_to=landed, error=exch.error, checked_at=now)
    return _finalize(url, exch, chain_final, exch.body,
                     error=_status_error(exch.status) if exch.status >= 400 else "",
                     latency_ms=latency_ms, now=now, origin=origin,
                     redirects_to=chain_final,
                     head=head if not need_get else None,
                     hint_ext=hint_ext)


def _status_error(status: int) -> str:
    if 400 <= status < 600:
        return f"http_{status}"
    return ""


def _finalize(url: str, exch: _Exchange, chain_final: str, body: bytes, *,
              error: str, latency_ms: int, now: float, origin: str,
              redirects_to: str, head: _Exchange | None = None,
              head_only: bool = False, hint_ext: str = "") -> ProbeResult:
    """Fold one response into a :class:`ProbeResult` (the product contract)."""
    status = exch.status
    meta_headers = dict(exch.headers)
    if head is not None and head is not exch:
        for k, v in head.headers.items():
            meta_headers.setdefault(k, v)
    ctype = _normalize_content_type(_header_get(meta_headers, "content-type")
                                    or _header_get(exch.headers, "content-type"))
    ext = (_extension(urllib.parse.urlsplit(chain_final).path
                      or urllib.parse.urlsplit(url).path) or hint_ext)
    sniffed = _sniff(body) if body else ""
    by_ext = ext in _HLS_EXT or ext in _DASH_EXT or ext in _PROGRESSIVE_EXT

    if status >= 400 or error:
        protocol = "unusable"
    elif head_only and (ctype in _HTML_CT or (not by_ext and not sniffed)):
        # no body evidence available: an HTML page is reported as a page, and we
        # cannot tell an embed bridge from a plain article without the body.
        protocol = "html_page" if ctype in _HTML_CT else _classify(ext, ctype, b"")
    else:
        protocol = _classify(ext, ctype, body)
        if protocol == "unusable" and sniffed:
            protocol = sniffed

    size = _total_size(exch)

    # range policy: 206 proves it; a 200 that ignores Range only proves it when
    # the server also says Accept-Ranges: bytes.
    aranges = "bytes" in _header_get(meta_headers, "accept-ranges").lower()
    accepts_ranges = (status == 206) or (status == 200 and aranges)

    cors_open = False
    acao = _header_get(meta_headers, "access-control-allow-origin")
    if acao:
        acao_norm = acao.strip().lower()
        cors_open = acao_norm == "*" or acao_norm == origin

    if not error:
        if status == 200 and not body and not size and not head_only:
            error = "empty_body"
            protocol = "unusable"
        elif protocol == "unusable":
            error = "not_media"

    streamable = (protocol in STREAMABLE_PROTOCOLS and not error
                  and (size > 0 or protocol == "hls"))
    downloadable = ((protocol == "progressive" and not error)
                    or (protocol == "hls" and _hls_has_media(body)))
    resumable = bool(accepts_ranges and downloadable)

    speed = 0.0
    if not error and body and len(body) >= MIN_SAMPLE_FOR_SPEED and exch.body_ms > 0:
        speed = round(len(body) * 8 / (exch.body_ms / 1000.0) / 1e6, 2)

    # A redirect that lands on a different host than the stored final_url is
    # still usable (ok stays True); the move is recorded in redirects_to, so
    # callers compare _host_of(redirects_to) against final_url to re-canon.
    return ProbeResult(
        url=url,
        ok=bool(status < 400 and protocol != "unusable" and not error),
        http_status=status,
        protocol=protocol,
        content_type=ctype,
        size_bytes=int(size or 0),
        accepts_ranges=bool(accepts_ranges),
        resumable=resumable,
        cors_open=bool(cors_open),
        latency_ms=int(latency_ms),
        download_speed_mbps=float(speed),
        streamable=bool(streamable),
        downloadable=bool(downloadable),
        redirects_to=redirects_to if redirects_to != url else "",
        error=error,
        checked_at=float(now),
    )


def _host_of(url: str) -> str:
    try:
        return (urllib.parse.urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


# ── scoring ──────────────────────────────────────────────────────────────────

_TIER_WEIGHTS = {1: 1.0, 2: 0.7, 3: 0.4}


def score_link(result: ProbeResult, *, playback_type: str = "",
               is_temporary: int = 0, service_tier: int = 1) -> int:
    """Rank a probed link 0..1000 — playability beats speed beats freshness.

    Implemented formula (additive, then clamped)::

        0                                    when result.ok is False
        +300  streamable                     (the app can actually play it)
        +150  downloadable                   (a file the user can keep)
        +100  accepts_ranges                 (resume after a drop on mobile)
        +80   cors_open                      (WebView / ExoPlayer can fetch it)
        +100  * min(speed_mbps, 20) / 20      (20 Mbps saturates any handset)
        +100  * clamp((3000 - latency_ms) / (3000 - 150))  (full at <=150 ms,
                                             zero at >=3000 ms, linear between)
        +100  * tier_weight                  (tier1=1.0, tier2=0.7, tier3=0.4)
        -150  when is_temporary              (ephemeral tokens rot overnight)
        -100  when protocol == "embed"        (a page, not a stream)

    Rationale for the ordering: a link the player can open is worth more than
    any amount of bandwidth (300 for streamable dominates every speed and
    latency term), because the app's failure mode is "nothing plays", not
    "it buffered". Resumability (100) sits above CORS (80) since a drop on a
    train is the common complaint, and speed, latency and tier are each scaled
    0..100 so no single one of them can ever promote a non-streamable link past
    a streamable one. Temporary links and embed pages are punished because they
    age badly and the client cannot render them directly.

    With these weights the practical ceiling is 930 (every bonus earned, tier 1)
    and the practical floor for a live-but-unplayable page is 0; the 0..1000
    clamp is deliberate headroom for future bonuses, not a reachable score.

    ``playback_type`` ('url'|'download'|'direct') is part of the signature for
    ranking variants but intentionally does not change this documented formula:
    the score is protocol-driven, so the same probe always scores the same.
    """
    if result is None or not getattr(result, "ok", False):
        return 0
    points = 0.0
    if result.streamable:
        points += 300
    if result.downloadable:
        points += 150
    if result.accepts_ranges:
        points += 100
    if result.cors_open:
        points += 80
    points += min(max(result.download_speed_mbps, 0.0), 20.0) / 20.0 * 100.0
    lat = max(result.latency_ms, 0)
    points += max(0.0, min(1.0, (3000 - lat) / (3000 - 150))) * 100.0
    points += _TIER_WEIGHTS.get(int(service_tier), 0.4 if int(service_tier) > 3 else 1.0) * 100.0
    if is_temporary:
        points -= 150
    if result.protocol == "embed":
        points -= 100
    return max(0, min(1000, int(round(points))))


# ── aggregates & history ─────────────────────────────────────────────────────

def summarize(results: list[ProbeResult]) -> dict:
    """Batch rollup for the ops dashboard / ``health-check`` CLI output."""
    results = list(results or [])
    total = len(results)
    by_protocol: dict[str, int] = {}
    by_error: dict[str, int] = {}
    ok_count = stream = down = resume = cors = 0
    lat_sum = 0
    speed_sum = 0.0
    for r in results:
        by_protocol[r.protocol] = by_protocol.get(r.protocol, 0) + 1
        if r.error:
            by_error[r.error] = by_error.get(r.error, 0) + 1
        ok_count += 1 if r.ok else 0
        stream += 1 if r.streamable else 0
        down += 1 if r.downloadable else 0
        resume += 1 if r.resumable else 0
        cors += 1 if r.cors_open else 0
        lat_sum += max(r.latency_ms, 0)
        speed_sum += max(r.download_speed_mbps, 0.0)
    return {
        "total": total,
        "ok": ok_count,
        "failed": total - ok_count,
        "streamable": stream,
        "downloadable": down,
        "resumable": resume,
        "cors_open": cors,
        "by_protocol": by_protocol,
        "by_error": by_error,
        "avg_latency_ms": int(round(lat_sum / total)) if total else 0,
        "avg_speed_mbps": round(speed_sum / total, 2) if total else 0.0,
        "ok_ratio": round(ok_count / total, 4) if total else 0.0,
    }


def merge_health_history(previous: dict, newest: ProbeResult,
                         *, weight: float = 0.4) -> dict:
    """Blend one probe into a rolling EWMA record so ops can stop re-probing.

    ``previous`` shape (missing keys / ``None`` are fine)::

        {"checks": int, "success_ema": float, "latency_ms_ema": int,
         "speed_mbps_ema": float, "last_error": str, "last_checked": float}

    ``weight`` is the newest sample's share, clamped to 0..1, so a link that
    starts failing decays toward 0 fast: after one failed check at weight 0.4
    ``success_ema`` is 0.6, after two it is 0.36, after three 0.216. The
    returned dict is always a new object — the caller's dict is never mutated.

    Latency and speed are only blended when the newest sample actually measured
    them (``latency_ms > 0``): a timeout or a refused connection has no timing
    data, and averaging a fake 0 ms in would make a dying link look faster.
    """
    weight = max(0.0, min(1.0, float(weight)))
    prev = dict(previous or {})
    success = 1.0 if (newest is not None and newest.ok) else 0.0
    latency = max(int(newest.latency_ms or 0), 0) if newest else 0
    speed = max(float(newest.download_speed_mbps or 0.0), 0.0) if newest else 0.0
    measured = latency > 0
    checks = int(prev.get("checks") or 0) + (1 if newest is not None else 0)
    prev_success = prev.get("success_ema")

    if checks <= 1 or prev_success is None:
        merged = {"success_ema": success,
                  "latency_ms_ema": latency if measured else int(prev.get("latency_ms_ema") or 0),
                  "speed_mbps_ema": speed if measured else float(prev.get("speed_mbps_ema") or 0.0)}
    else:
        keep = 1.0 - weight
        merged = {
            "success_ema": round(float(prev_success) * keep + success * weight, 6),
            "latency_ms_ema": int(round(float(prev.get("latency_ms_ema") or 0) * keep
                                        + latency * weight)) if measured
            else int(prev.get("latency_ms_ema") or 0),
            "speed_mbps_ema": round(float(prev.get("speed_mbps_ema") or 0.0) * keep
                                    + speed * weight, 4) if measured
            else round(float(prev.get("speed_mbps_ema") or 0.0), 4),
        }
    return {
        "checks": checks,
        "success_ema": merged["success_ema"],
        "latency_ms_ema": merged["latency_ms_ema"],
        "speed_mbps_ema": merged["speed_mbps_ema"],
        "last_error": (newest.error if newest else "") or "",
        "last_checked": float(newest.checked_at) if newest and newest.checked_at
        else float(prev.get("last_checked") or 0.0),
    }


# ── batch probing ────────────────────────────────────────────────────────────

def _is_blocklisted(url: str, blocklist) -> bool:
    host = _host_of(url)
    for raw in blocklist or ():
        if not isinstance(raw, str):
            continue
        pat = raw.strip().lower()
        if not pat:
            continue
        if pat.startswith("*"):
            if host.endswith(pat[1:].lstrip(".")):
                return True
        elif host == pat or host.endswith("." + pat):
            return True
        elif "/" in pat and pat in url.lower():
            return True
    return False


def probe_many(links: list[dict], *, workers: int = 8,
               timeout: float = DEFAULT_TIMEOUT, sample_bytes: int = DEFAULT_SAMPLE_BYTES,
               url_blocklist=None, allow_private: bool = False) -> list[ProbeResult]:
    """Probe *links* concurrently, returning results in input order.

    Each item is a dict::

        {"url": str, "final_url": str, "headers": dict, "service": str,
         "allow_private": bool}

    Only the worker's own arguments and an immutable :class:`ProbeResult` ever
    cross thread boundaries — no shared mutable state, so the pool is safe to
    call from the API server. A worker that explodes (killed server, half-open
    socket) still yields an ``ok=False`` result rather than raising out of the
    batch. ``url_blocklist`` names hosts (``"dropgalaxy.vip"``, ``".tk"``) or
    substrings to skip for known-hostile services; skipped links report
    ``error="blocklisted"`` without touching the network.
    """
    links = list(links or [])
    if not links:
        return []
    pool_size = max(1, min(int(workers or 1), len(links)))

    def _one(link: dict) -> ProbeResult:
        if not isinstance(link, dict):
            link = {"url": str(link)}
        url = link.get("url") or ""
        if _is_blocklisted(url, url_blocklist):
            return ProbeResult(url=url, error="blocklisted",
                               checked_at=time.time())
        kwargs = {"timeout": link.get("timeout", timeout),
                  "sample_bytes": link.get("sample_bytes", sample_bytes),
                  "allow_private": bool(link.get("allow_private", allow_private))}
        if link.get("final_url"):
            kwargs["final_url"] = link["final_url"]
        if link.get("headers"):
            kwargs["headers"] = link["headers"]
        if link.get("service"):
            kwargs["service"] = link["service"]
        try:
            return probe(url, **kwargs)
        except TypeError:
            raise
        except Exception as exc:  # defensive: never leak a batch failure
            return ProbeResult(url=url, error=f"conn_error:{type(exc).__name__}",
                               checked_at=time.time())

    with concurrent.futures.ThreadPoolExecutor(max_workers=pool_size) as pool:
        return list(pool.map(_one, links))


if __name__ == "__main__":  # tiny manual smoke: python -S Fast_Fetch/link_health.py URL
    import sys

    target = sys.argv[1] if len(sys.argv) > 1 else ""
    if not target:
        print("usage: link_health.py <url>")
    else:
        res = probe(target)
        print(f"{res.protocol:<11} status={res.http_status} size={res.size_bytes} "
              f"ranges={int(res.accepts_ranges)} cors={int(res.cors_open)} "
              f"{res.latency_ms}ms {res.download_speed_mbps}Mbps "
              f"score={score_link(res)} error={res.error or '-'}")
