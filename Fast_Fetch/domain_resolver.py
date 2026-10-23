"""
Domain Resolver & Auto-Discovery Engine for Radd-Stream.

Maintains live site health, tracks active domains, follows HTTP 301/302 redirects,
and provides auto-failover to backup mirrors without manual script modifications.
100% Python Standard Library. Zero external dependencies.
"""

import json
import os
import ssl
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
REGISTRY_PATH = BASE_DIR / "domain_registry.json"

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"


def _get_ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def load_registry() -> dict:
    if not REGISTRY_PATH.exists():
        return {"version": "1.0", "sites": {}}
    try:
        with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"version": "1.0", "sites": {}}


def save_registry(data: dict) -> None:
    data["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with open(REGISTRY_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def get_active_base_url(site_name: str, fallback_default: str | None = None) -> str:
    """Returns the current verified active base URL for a given site from registry."""
    reg = load_registry()
    site_info = reg.get("sites", {}).get(site_name)
    if site_info and site_info.get("active_base_url"):
        return site_info["active_base_url"]
    return fallback_default or ""


def probe_site(site_name: str, auto_update: bool = True) -> dict:
    """
    Probes the active domain for a site. Follows redirects.
    If down, attempts alternate mirrors from known_mirrors.
    Returns status dict with live URL, status code, and latency.
    """
    reg = load_registry()
    site_info = reg.get("sites", {}).get(site_name)
    if not site_info:
        return {"site": site_name, "status": "unknown", "error": "Site not in registry"}

    ctx = _get_ssl_context()
    active_url = site_info.get("active_base_url", "")
    known_mirrors = site_info.get("known_mirrors", [active_url])
    api_endpoint = site_info.get("api_endpoint") or site_info.get("sitemap_endpoint") or ""

    candidates = [active_url] + [m for m in known_mirrors if m != active_url]

    for candidate in candidates:
        if not candidate:
            continue
        test_url = candidate.rstrip("/") + (api_endpoint if api_endpoint.startswith("/") else f"/{api_endpoint}")
        if not api_endpoint:
            test_url = candidate

        t0 = time.time()
        try:
            req = urllib.request.Request(test_url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
                code = resp.status
                final_url = resp.geturl()
                elapsed = time.time() - t0

                # Detect if domain changed via redirect
                parsed_orig = urllib.parse.urlparse(candidate)
                parsed_final = urllib.parse.urlparse(final_url)
                final_base = f"{parsed_final.scheme}://{parsed_final.netloc}"

                domain_shifted = parsed_orig.netloc.lower() != parsed_final.netloc.lower()

                if auto_update and (domain_shifted or final_base != active_url):
                    site_info["active_base_url"] = final_base
                    if final_base not in site_info.setdefault("known_mirrors", []):
                        site_info["known_mirrors"].append(final_base)
                    site_info["status"] = "active"
                    save_registry(reg)

                return {
                    "site": site_name,
                    "status": "active",
                    "status_code": code,
                    "candidate_tested": candidate,
                    "final_base_url": final_base,
                    "domain_shifted": domain_shifted,
                    "latency_sec": round(elapsed, 2),
                }
        except Exception as e:
            continue

    if auto_update:
        site_info["status"] = "down"
        save_registry(reg)

    return {
        "site": site_name,
        "status": "down",
        "error": "All candidates failed",
        "tested_candidates": candidates,
    }


def probe_all_sites() -> list[dict]:
    """Probes all configured sites and returns audit summary."""
    reg = load_registry()
    results = []
    for site_name in sorted(reg.get("sites", {}).keys()):
        res = probe_site(site_name, auto_update=True)
        results.append(res)
    return results


if __name__ == "__main__":
    print("=" * 70)
    print(" 🌐 Radd-Stream Fleet Domain Health & Auto-Discovery Prober")
    print("=" * 70)
    results = probe_all_sites()
    for r in results:
        status_icon = "✅" if r.get("status") == "active" else "❌"
        shift = " (🔄 Shifted)" if r.get("domain_shifted") else ""
        code = r.get("status_code", "ERR")
        url = r.get("final_base_url") or r.get("candidate_tested") or "N/A"
        lat = f"{r.get('latency_sec', 0.0)}s"
        print(f" {status_icon} {r['site']:<14} | HTTP {code:<3} | {lat:<6} | {url}{shift}")
    print("=" * 70)
