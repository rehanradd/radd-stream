"""Real domain health checker for Admin Panel v2.

Checks, in order, DNS -> TCP (443) -> TLS -> HTTPS page, with a
fingerprint step on the page body. Stdlib only, no external assets.

Redirects are FOLLOWED (up to 5 hops) and the FINAL body is what gets
fingerprinted — the old code fingerprinted the redirect body itself,
so a 301/302 to a moved, parked or hijacked domain passed as healthy
(admin-panel audit 2026-11-08 §Domains: 12 of 18 stale domains read
"healthy"). A redirect to a host that does not contain the site slug
is a hijack/doorway, not a pass.

Content-kind rules (domain-tracking design §5): a bare 200 proves
nothing. The final page must be HTML with a title, carry no parking
or bot-challenge markers, be at least 2,000 bytes (doorway pages are
tiny — vegamovies.xyz was 114 bytes), and show positive content
evidence for the site (slug in the <title>, >=3 internal links, or a
quality marker like 720p/1080p). A Cloudflare challenge is
`bot_challenge` (unverifiable, not dead) — never a pass.

Safety rules (do not weaken):
- TLS is verified with the default context. No cert bypass, ever.
- Only the first 64 KiB of the page body is read. Never downloads a file.
- Redirects to plain http are refused, never followed.
- Fingerprint without an expected marker is a heuristic only: a real
  HTML page with a title and no parking markers. With an expected
  marker (owner-supplied, e.g. a word from the site's own homepage),
  fingerprint_ok means that marker is present in the body.
- Returned dict keys match what Service.validate_domain reads:
  dns_ok, tcp_ok, tls_ok, http_status, fingerprint_ok, latency_ms,
  failure_reason — plus final_domain (the host actually fingerprinted),
  redirected and redirect_count. No IP addresses or body content are
  returned.
"""

import http.client
import re
import socket
import ssl
import time
import urllib.parse

READ_LIMIT = 65536
MAX_REDIRECTS = 5
MIN_BODY_BYTES = 2000
PARKING_MARKERS = (
    "domain is for sale",
    "buy this domain",
    "this domain is parked",
    "domain parking",
    "parked domain",
    "sedo",
    "afternic",
    "dan.com",
    "hugedomains",
    "bodis",
    "parkingcrew",
    "is for sale",
    "this domain has expired",
)
CHALLENGE_MARKERS = (
    "just a moment",
    "attention required",
    "verify you are human",
    "are you a robot",
)
# Quality markers a real movie/series homepage carries (design §5:
# post titles carry 480p/720p/1080p/WEB-DL). One of these, a slug in
# the <title>, or >=3 internal links counts as content evidence.
QUALITY_MARKERS = (
    b"480p", b"720p", b"1080p", b"2160p", b"web-dl", b"webdl",
    b"bluray", b"blu-ray", b"hdts", b"hdtc", b"hevc", b"hdtv",
)
REDIRECT_STATUSES = (301, 302, 303, 307, 308)
_TITLE_RE = re.compile(rb"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_HREF_RE = re.compile(rb'href\s*=\s*["\']([^"\']+)', re.IGNORECASE)


def _slug(site_key):
    return (site_key or "").lower().replace("_", "").replace("-", "")


def _internal_link_count(body, final_host):
    host = (final_host or "").lower().encode()
    count = 0
    for href in _HREF_RE.findall(body or b""):
        h = href.lower()
        if h.startswith(b"/") and not h.startswith(b"//"):
            count += 1
        elif host and h.startswith(b"http") and host in h:
            count += 1
    return count


def fingerprint_check(body, content_type, expected_marker=None,
                      site_key=None, final_host=None):
    """(ok, reason): the content-kind verdict for one fetched body.

    reason is None on a pass, else one of: marker_missing, empty_body,
    not_html, no_html_title, parked, bot_challenge, redirect_hijack,
    content_too_small, no_content_evidence.
    """
    if expected_marker:
        marker = expected_marker.encode() if isinstance(expected_marker, str) else expected_marker
        if marker.lower() in (body or b"").lower():
            return True, None
        return False, "marker_missing"
    if not body:
        return False, "empty_body"
    if "text/html" not in (content_type or "").lower():
        return False, "not_html"
    text = body.lower()
    if b"<html" not in text and b"<title" not in text:
        return False, "no_html_title"
    for marker in PARKING_MARKERS:
        if marker.encode() in text:
            return False, "parked"
    for marker in CHALLENGE_MARKERS:
        if marker.encode() in text:
            return False, "bot_challenge"
    slug = _slug(site_key)
    host = (final_host or "").lower()
    if slug and host and slug not in host:
        # Final host after redirects is not the site at all (design §5:
        # desicinemas.tv -> koi5000sultan.com). Hijack/doorway, not a pass.
        return False, "redirect_hijack"
    if len(body) < MIN_BODY_BYTES:
        return False, "content_too_small"
    if slug:
        title_m = _TITLE_RE.search(body)
        title = title_m.group(1).lower() if title_m else b""
        has_title_slug = slug.encode() in title
        has_links = _internal_link_count(body, host) >= 3
        has_quality = any(m in text for m in QUALITY_MARKERS)
        if not (has_title_slug or has_links or has_quality):
            return False, "no_content_evidence"
    return True, None


def fingerprint_ok_for_body(body, content_type, expected_marker=None):
    """Backwards-compatible bool wrapper around fingerprint_check."""
    ok, _reason = fingerprint_check(body, content_type, expected_marker)
    return ok


def check_domain(domain, timeout=8.0, expected_marker=None, site_key=None):
    """Probe one domain. Returns the dict Service.validate_domain reads."""
    started = time.monotonic()
    result = {
        "dns_ok": False,
        "tcp_ok": False,
        "tls_ok": False,
        "http_status": None,
        "fingerprint_ok": False,
        "latency_ms": 0,
        "failure_reason": None,
        "final_domain": domain,
        "redirected": False,
        "redirect_count": 0,
    }

    def finish(reason=None):
        result["latency_ms"] = int((time.monotonic() - started) * 1000)
        result["failure_reason"] = reason
        return result

    host = domain
    hops = 0
    body = b""
    content_type = ""
    while True:
        try:
            socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
        except (socket.gaierror, UnicodeError, ValueError):
            return finish("dns_failed")
        result["dns_ok"] = True

        try:
            raw = socket.create_connection((host, 443), timeout=timeout)
        except OSError:
            return finish("tcp_failed")
        result["tcp_ok"] = True

        context = ssl.create_default_context()
        try:
            tls = context.wrap_socket(raw, server_hostname=host)
        except (ssl.SSLError, OSError):
            raw.close()
            return finish("tls_failed")
        result["tls_ok"] = True
        try:
            tls.close()
        except OSError:
            pass

        try:
            conn = http.client.HTTPSConnection(host, 443, timeout=timeout, context=context)
            conn.request("GET", "/", headers={
                "User-Agent": "RaddStream-Admin-Health/1.0",
                "Accept": "text/html",
            })
            resp = conn.getresponse()
            body = resp.read(READ_LIMIT + 1)[:READ_LIMIT]
            result["http_status"] = resp.status
            location = resp.getheader("Location")
            content_type = resp.getheader("Content-Type", "")
            conn.close()
        except (OSError, http.client.HTTPException):
            return finish("http_failed")

        if resp.status in REDIRECT_STATUSES and location:
            if hops >= MAX_REDIRECTS:
                return finish("redirect_loop")
            nxt = urllib.parse.urlparse(
                urllib.parse.urljoin("https://%s/" % host, location))
            if nxt.scheme != "https" or not nxt.hostname:
                return finish("redirect_to_http")
            hops += 1
            result["redirected"] = True
            result["redirect_count"] = hops
            host = nxt.hostname
            result["final_domain"] = host
            continue
        break

    result["http_ok"] = result["http_status"] == 200
    if result["http_status"] != 200:
        return finish("http_failed")
    ok, reason = fingerprint_check(body, content_type, expected_marker,
                                   site_key=site_key, final_host=host)
    if not ok:
        return finish(reason)
    result["fingerprint_ok"] = True
    return finish(None)
