#!/usr/bin/env python3
"""
bridge_tracer.py — Spec Phase 2: read-only link/redirect graph tracer.

Follows a single starting URL 1-2 hops deep using urllib.request with automatic
redirect-following DISABLED, so every hop in the chain is visible as its own
record. At each hop it detects the *known unwrap patterns the project already
implements* (see fast_fetch.py's unwrap_pixeldrain / unwrap_mobilejsr /
unwrap_greenmotors / unwrap_vcloud / unwrap_fastdl / unwrap_hubcloud /
unwrap_direct_cloud) and reports which marker matched.

STRICT SAFETY BOUNDARIES (enforced in code, not just comments):
  * READ-ONLY. Every request is a GET. This module NEVER sends a request body,
    never does cookie/CSRF/POST token negotiation, and never submits credentials.
    (contrast fast_fetch.unwrap_direct_cloud / unwrap_mobilejsr which POST.)
  * Purely local base64/rot13 decoding of payload text that is already present in
    a fetched page is allowed (deterministic, no I/O, no side effects); an actual
    JS challenge is NOT attempted — a challenge interstitial is reported as
    blocked: challenge and the trace stops there.
  * Must NEVER be invoked from a public HTTP route (viewer.py / catalog_api.py).
    This is an operator-side reconnaissance tool only.

Python standard library ONLY. No pip, no third-party imports.

Usage:
    python3 -S Fast_Fetch/bridge_tracer.py https://hubcloud.ist/drive/ABC123 [--hops 2]
"""

from __future__ import annotations

import argparse
import base64
import codecs
import json
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import site_scout  # reuse UA, registry, classifier, ssl ctx (stdlib only)

USER_AGENT = site_scout.BROWSER_UA

READ_ONLY = True  # documentation flag: this tracer is GET-only by construction.

CHALLENGE_MARKERS = site_scout.CHALLENGE_MARKERS


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Stop urllib from following 3xx so the tracer sees the hop structure."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def make_ssl_ctx() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _build_opener(ssl_ctx: ssl.SSLContext):
    handlers = [urllib.request.HTTPSHandler(context=ssl_ctx), urllib.request.HTTPHandler(), _NoRedirect()]
    return urllib.request.build_opener(*handlers)


def is_challenge_interstitial(html: str) -> bool:
    return site_scout.is_challenge_interstitial(html)


# ---------------------------------------------------------------------------
# Known unwrap-pattern detectors (pure functions over a URL and/or page HTML).
# They mirror fast_fetch.py's unwrappers but only DETECT / decode locally.
# ---------------------------------------------------------------------------

PATTERNS = (
    ("pixeldrain_direct", r"pixeldrain\.com/(?:u|d|api/file)/([A-Za-z0-9_-]+)"),
    ("hubcloud_drive", r"hubcloud\.[a-z]+/drive/([A-Za-z0-9_-]+)"),
    ("hubcloud_gpdl", r"(?:gpdl[0-9]*\.)?hubcloud\.[a-z]+/\?id=([A-Za-z0-9_-]+)"),
    ("mobilejsr_view", r"mobilejsr\.com/view/([A-Za-z0-9_-]+)"),
    ("mobilejsr_embed", r"mobilejsr\.com/embed/([A-Za-z0-9_-]+)"),
    ("greenmotors_bridge", r"greenmotors\.[a-z]+/\?id=([A-Za-z0-9+/=_\-]+)"),
    ("vcloud_token", r"vcloud\.[a-z]+/([A-Za-z0-9_-]+)"),
    ("fastdl_reurl", r"fastdl\.[a-z]+/dl\.php\?link=([^\"'\s]+)"),
    ("fastdl_embed", r"fastdl\.[a-z]+/embed\.php\?download=([A-Za-z0-9_-]+)"),
    ("linkszilla_view", r"linkszilla\.[a-z]+/view/([A-Za-z0-9_-]+)"),
    ("nexdrive_genxfm", r"nexdrive\.[a-z]+/genxfm/([A-Za-z0-9_-]+)"),
    ("vegadrive_share", r"vegadrive\.[a-z]+/s/([A-Za-z0-9_-]+)"),
    ("filepress_file", r"filepress\.[a-z]+/file/([A-Za-z0-9_-]+)"),
    ("gofile_share", r"gofile\.io/d/([A-Za-z0-9_-]+)"),
    ("gdflix_file", r"gdflix\.[a-z]+/file/([A-Za-z0-9_-]+)"),
    ("direct_cloud_view", r"direct-cloud\.[a-z]+/d/([A-Za-z0-9_-]+)"),
    ("hubcloud_api", r"gamerxyt\.com/hubcloud\.php\?[^\"'\s]+"),
    ("fastdl_var_reurl", r"var\s+reurl\s*=\s*[\"']([^\"']+)[\"']"),
    ("vcloud_atob_atob", r"atob\(\s*atob\(\s*['\"]([^'\"]+)['\"]\s*\)\s*\)"),
    ("greenmotors_s_o", r"s\(\s*['\"]o['\"]\s*,\s*['\"]([A-Za-z0-9+/=]+)['\"]"),
)

_COMPILED = [(name, re.compile(pat, re.I)) for name, pat in PATTERNS]


def detect_patterns(url: str, html: str = "") -> list:
    """Return [{'pattern', 'value', 'hint'}] for each known marker seen on this hop."""
    haystack_url = url or ""
    haystack_html = html or ""
    hits = []
    for name, rx in _COMPILED:
        source = haystack_html if rx.pattern.startswith(("var\\s", "atob", "s\\(")) else haystack_url
        m = rx.search(source)
        if not m:
            if rx.search(haystack_html):
                m = rx.search(haystack_html)
        if m:
            hits.append({
                "pattern": name,
                "value": (m.group(1) if m.groups() else m.group(0))[:120],
                "hint": _hint_for(name, m),
            })
    return hits


def _hint_for(name: str, m) -> str:
    hints = {
        "pixeldrain_direct": "rewrite to https://pixeldrain.com/api/file/<id> (direct, no JS)",
        "vegadrive_share": "rewrite to https://one.vegadrive.me/d/<id>/skyd (direct)",
        "mobilejsr_view": "same-id embed path /embed/<id> is stable and storable (no JS to persist)",
        "hubcloud_api": "gamerxyt relay returns R2 / 10Gbps anchors",
        "greenmotors_s_o": "payload is nested base64 + rot13; resolve requires JS — stored as bridge",
        "vcloud_atob_atob": "double base64 decodes locally to a token URL",
        "fastdl_var_reurl": "var reurl link= decodes to a Google CDN download URL",
        "greenmotors_bridge": "JS-rendered bridge — store as-is, do not urllib-resolve",
    }
    return hints.get(name, "known hoster marker")


def decode_greenmotors_payload(payload_b64: str) -> str | None:
    """Mirror fast_fetch.decode_greenmotors_payload (pure local decode)."""
    try:
        p1 = base64.b64decode(payload_b64).decode("utf-8", errors="replace")
        p2 = base64.b64decode(p1).decode("utf-8", errors="replace")
        p3 = codecs.decode(p2, "rot_13")
        p4 = base64.b64decode(p3).decode("utf-8", errors="replace")
        data = json.loads(p4)
        if isinstance(data, dict) and "o" in data:
            return base64.b64decode(data["o"]).decode("utf-8", errors="replace")
    except Exception:
        return None
    return None


def decode_vcloud_token(token_b64: str) -> str | None:
    try:
        d1 = base64.b64decode(token_b64).decode("utf-8", errors="ignore")
        return base64.b64decode(d1).decode("utf-8", errors="ignore")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# The tracer itself
# ---------------------------------------------------------------------------

class BridgeTracer:
    def __init__(self, *, opener=None, ssl_ctx=None, max_hops=2, timeout=15, kinds=None):
        self.ssl_ctx = ssl_ctx or make_ssl_ctx()
        self._opener = opener or _build_opener(self.ssl_ctx)
        self.max_hops = max(1, min(2, int(max_hops)))
        self.timeout = timeout
        self.kinds = kinds if kinds is not None else site_scout.build_kinds_map(site_scout.load_registry())

    def _get(self, url: str):
        """GET only. Returns (status, final_url, location, body_text). Never sends data."""
        req = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        })
        try:
            resp = self._opener.open(req, timeout=self.timeout)
            status = getattr(resp, "status", None) or resp.getcode()
            body = resp.read().decode("utf-8", errors="replace")
            final = resp.geturl() if hasattr(resp, "geturl") else url
            location = resp.headers.get("Location") if getattr(resp, "headers", None) else None
            try:
                resp.close()
            except Exception:
                pass
            return status, final, location, body
        except urllib.error.HTTPError as exc:
            location = exc.headers.get("Location") if getattr(exc, "headers", None) else None
            body = ""
            try:
                body = exc.read().decode("utf-8", errors="replace")
            except Exception:
                body = ""
            return exc.code, url, location, body
        except Exception as exc:
            return 0, url, None, f"[fetch-error] {exc}"

    def trace(self, start_url: str) -> dict:
        hops = []
        current = start_url
        blocked = False
        for depth in range(self.max_hops + 1):
            status, final, location, body = self._get(current)
            kind = site_scout.classify_href(current, self.kinds)
            hop = {
                "depth": depth,
                "url": current,
                "host": urllib.parse.urlparse(current).netloc,
                "status": status,
                "redirect_to": location if location else (final if final != current else None),
                "link_kind": kind,
                "patterns": detect_patterns(current, body),
                "read_only": True,
            }
            if is_challenge_interstitial(body):
                hop["note"] = "blocked: challenge"
                blocked = True
                hops.append(hop)
                break
            hops.append(hop)
            if not location or depth >= self.max_hops:
                break
            current = urllib.parse.urljoin(current, location)

        return {
            "start_url": start_url,
            "max_hops": self.max_hops,
            "read_only": True,
            "blocked": blocked,
            "final_url": hops[-1]["url"] if hops else start_url,
            "final_kind": hops[-1]["link_kind"] if hops else "unknown",
            "hop_chain": hops,
            "patterns_observed": sorted({p["pattern"] for h in hops for p in h["patterns"]}),
        }


def trace_link(url: str, *, opener=None, max_hops: int = 2, timeout: int = 15) -> dict:
    return BridgeTracer(opener=opener, max_hops=max_hops, timeout=timeout).trace(url)


def parse_args(argv=None):
    p = argparse.ArgumentParser(prog="bridge_tracer.py", description="Read-only redirect/unwrap tracer (Phase 2).")
    p.add_argument("url", help="Starting bridge/direct link URL")
    p.add_argument("--hops", type=int, default=2, help="Max hops to follow (1-2)")
    p.add_argument("--timeout", type=int, default=15)
    p.add_argument("--json", action="store_true", help="Full hop chain JSON")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    result = trace_link(args.url, max_hops=args.hops, timeout=args.timeout)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"start={result['start_url']} final={result['final_url']} kind={result['final_kind']} blocked={result['blocked']}")
        for h in result["hop_chain"]:
            pats = ",".join(p["pattern"] for p in h["patterns"]) or "-"
            print(f"  hop{h['depth']} [{h['status']}] {h['link_kind']:7s} {h['url']}  patterns={pats}")
        print(f"observed patterns: {result['patterns_observed']}")
    return result


if __name__ == "__main__":
    main()
