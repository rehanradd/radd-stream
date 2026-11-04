"""
Domain Resolver & Auto-Discovery Engine for Radd-Stream.

Maintains live site health, tracks active domains, follows HTTP 301/302
redirects, detects TLD rotations when a whole candidate set dies, and provides
auto-failover to backup mirrors without manual script modifications.
100% Python Standard Library. Zero external dependencies.

WRITE SAFETY (the registry is read by the running service):
  * ``save_registry`` is atomic — temp file in the same directory, fsync,
    ``os.replace``. A crash mid-write leaves the previous good file intact.
  * every mutation goes through ``update_site_registry``, which reloads the
    registry *under* an advisory ``flock`` and merges only the touched keys
    before saving. ``probe_site`` reads config up front but never writes back
    that pre-network snapshot, so a concurrent run's updates cannot be lost
    and a redirect-followed mirror cannot clobber unrelated sites.
  * a WAF/anti-bot refusal (401/403/405/429) is NOT "down": a blocked probe
    reports ``blocked`` and never changes the site record. Only network-level
    failure of every candidate can demote a site, and the active domain is
    only re-pointed when the old one actually failed this run.

CLI (this module's __main__ IS the monitor; do not build a second registry
writer — Crown-Prince order qoder14, Task B):
    python3 -S Fast_Fetch/domain_resolver.py [site_name ...]
"""

import contextlib
import fcntl
import json
import os
import ssl
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
REGISTRY_PATH = BASE_DIR / "domain_registry.json"

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

PROBE_TIMEOUT_SECONDS = 10

#: HTTP answers that mean "a server is there and refusing our client", not
#: "the domain died". A challenge/WAF must never retire a working domain.
BLOCKED_STATUS_CODES = frozenset({401, 403, 405, 429})

#: Bounded TLD sweep for rotation detection (host-power-weakness.md: these
#: sites rotate TLDs — 10xflix.hair, 7starhd.dentist, 9xmovie.bayern are in
#: the live registry — and a rotation usually comes WITHOUT an HTTP redirect,
#: so redirect-following alone never sees it). Deliberately short: this list
#: multiplies probes-per-dead-site.
ROTATION_TLDS = (".com", ".net", ".org", ".to", ".io", ".gg", ".xyz",
                 ".tv", ".win", ".life", ".fun", ".click", ".cc", ".in",
                 ".biz", ".info", ".world", ".shop", ".cloud", ".run",
                 ".bar", ".top", ".live")


def _get_ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


# ---------------------------------------------------------------------------
# Registry I/O — one writer, atomic, lock-protected
# ---------------------------------------------------------------------------


def _registry_path() -> Path:
    """Indirection so tests can point at a temp registry without patching
    module constants twice over."""
    return REGISTRY_PATH


def load_registry(path: Path | None = None) -> dict:
    p = path or _registry_path()
    if not p.exists():
        return {"version": "1.0", "sites": {}}
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("sites"), dict):
            return data
        return {"version": "1.0", "sites": {}}
    except Exception:
        return {"version": "1.0", "sites": {}}


def save_registry(data: dict, path: Path | None = None) -> None:
    """Atomic write: temp file in the target directory + fsync + os.replace.

    json.dump runs BEFORE the replace, so any serialisation crash leaves the
    previous file untouched. The temp file is unlinked on failure.
    """
    p = path or _registry_path()
    data["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=str(p.parent),
                prefix=p.name + ".", suffix=".tmp", delete=False) as fh:
            tmp = Path(fh.name)
            json.dump(data, fh, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, p)
    except BaseException:
        if tmp is not None:
            with contextlib.suppress(OSError):
                tmp.unlink()
        raise


@contextlib.contextmanager
def _registry_lock(path: Path | None = None):
    """Advisory exclusive flock on a sidecar ``<registry>.lock`` file.

    Never locks the registry itself: the replace in save_registry swaps the
    inode, which silently detaches any lock held on it.
    """
    p = path or _registry_path()
    lock_path = Path(str(p) + ".lock")
    fh = open(lock_path, "w")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        fh.close()


def update_site_registry(site_name: str, changes: dict) -> dict:
    """Reload under lock, merge ``changes`` into that site's record, atomic
    save. Returns the merged site record.

    This is the ONLY sanctioned mutation path: reload-after-lock means the
    snapshot a caller read before its network work can never be written back
    wholesale over another run's updates.
    """
    with _registry_lock():
        reg = load_registry()
        sites = reg.setdefault("sites", {})
        site = sites.setdefault(site_name, {})
        for key, value in changes.items():
            if isinstance(value, list) and key == "known_mirrors":
                merged = list(site.get("known_mirrors", []))
                for item in value:
                    if item and item not in merged:
                        merged.append(item)
                site["known_mirrors"] = merged
            else:
                site[key] = value
        save_registry(reg)
        return site


def get_active_base_url(site_name: str, fallback_default: str | None = None) -> str:
    """Returns the current verified active base URL for a given site from registry."""
    reg = load_registry()
    site_info = reg.get("sites", {}).get(site_name)
    if site_info and site_info.get("active_base_url"):
        return site_info["active_base_url"]
    return fallback_default or ""


# ---------------------------------------------------------------------------
# Probing
# ---------------------------------------------------------------------------


def _fetch_final(test_url: str, opener=None):
    """GET ``test_url`` following redirects. Returns (status_code, final_url)
    or raises. ``opener`` is an injectable callable(url, timeout, ctx) with
    the same contract as urllib.request.urlopen — tests stub the network with
    it; production passes nothing."""
    req = urllib.request.Request(
        test_url, headers={"User-Agent": USER_AGENT})
    if opener is not None:
        resp = opener(req, PROBE_TIMEOUT_SECONDS)
    else:
        resp = urllib.request.urlopen(req, timeout=PROBE_TIMEOUT_SECONDS,
                                      context=_get_ssl_context())
    with contextlib.closing(resp):
        return resp.status, resp.geturl()


def _base_of(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _rotation_candidates(candidates: list[str]) -> list[str]:
    """Same host label, other TLDs — the rotation the sites actually perform
    (vegamovies.foo -> vegamovies.bar). Only the registered TLDs are swapped,
    each candidate once, bounded by ROTATION_TLDS."""
    seen = set()
    out = []
    for candidate in candidates:
        if not candidate:
            continue
        netloc = urllib.parse.urlparse(candidate).netloc.lower()
        if "." not in netloc:
            continue
        label, _, tld = netloc.rpartition(".")
        if not label or tld in ("", netloc):
            continue
        for new_tld in ROTATION_TLDS:
            if new_tld == "." + tld:
                continue
            rotated = label + new_tld
            if rotated in seen:
                continue
            seen.add(rotated)
            parsed = urllib.parse.urlparse(candidate)
            out.append(f"{parsed.scheme}://{rotated}" + parsed.path)
    return out


def probe_site(site_name: str, auto_update: bool = True, opener=None,
                rotate: bool = True) -> dict:
    """
    Probes the active domain for a site. Follows redirects; on a whole-set
    network failure it sweeps TLD rotations (if ``rotate``) before declaring
    the site down. A blocked (401/403/405/429) answer is reported as
    ``blocked`` and never touches the registry.

    Registry mutations go through update_site_registry (lock + reload +
    atomic save) — never by writing back the snapshot read at function entry.
    Returns status dict with live URL, status code, and latency.
    """
    reg = load_registry()
    site_info = reg.get("sites", {}).get(site_name)
    if not site_info:
        return {"site": site_name, "status": "unknown", "error": "Site not in registry"}

    active_url = site_info.get("active_base_url", "")
    known_mirrors = site_info.get("known_mirrors", [active_url])
    api_endpoint = site_info.get("api_endpoint") or site_info.get("sitemap_endpoint") or ""

    candidates = [active_url] + [m for m in known_mirrors if m != active_url]

    active_failed = False
    blocked_seen = None
    for candidate in candidates:
        if not candidate:
            continue
        test_url = candidate.rstrip("/") + (api_endpoint if api_endpoint.startswith("/") else f"/{api_endpoint}")
        if not api_endpoint:
            test_url = candidate

        t0 = time.time()
        try:
            code, final_url = _fetch_final(test_url, opener=opener)
        except urllib.error.HTTPError as e:
            if e.code in BLOCKED_STATUS_CODES:
                if candidate == active_url:
                    blocked_seen = e.code
                continue
            active_failed = active_failed or candidate == active_url
            continue
        except Exception:
            active_failed = active_failed or candidate == active_url
            continue
        elapsed = time.time() - t0

        final_base = _base_of(final_url)
        parsed_orig = urllib.parse.urlparse(candidate)
        parsed_final = urllib.parse.urlparse(final_url)
        domain_shifted = parsed_orig.netloc.lower() != parsed_final.netloc.lower()

        # Retire-the-active guard: re-point active_base_url only when the
        # stored active itself failed earlier in THIS run. A redirect off a
        # backup mirror while the active still answers must never move the
        # site record onto the mirror.
        if (auto_update and domain_shifted and active_failed
                and final_base and final_base != active_url):
            mirrors = site_info.get("known_mirrors", [])
            additions = [m for m in [active_url] if m and m not in mirrors]
            update_site_registry(site_name, {
                "active_base_url": final_base,
                "known_mirrors": additions,
                "status": "active",
                "last_rotated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                 time.gmtime()),
            })
        elif auto_update and final_base == active_url:
            update_site_registry(site_name, {"status": "active"})

        return {
            "site": site_name,
            "status": "active",
            "status_code": code,
            "candidate_tested": candidate,
            "final_base_url": final_base,
            "domain_shifted": domain_shifted,
            "active_repointed": bool(auto_update and domain_shifted
                                     and active_failed),
            "latency_sec": round(elapsed, 2),
        }

    # Nothing answered with 2xx/3xx. If the active itself was merely blocked
    # by a WAF, the domain is NOT dead: report blocked, change nothing.
    if blocked_seen is not None:
        return {
            "site": site_name,
            "status": "blocked",
            "status_code": blocked_seen,
            "error": "active domain refuses our client; health unknown, "
                     "registry untouched",
            "tested_candidates": candidates,
        }

    # TLD-rotation sweep: sites here rotate TLDs without redirects, so a dead
    # candidate set is exactly where rotation is visible.
    if rotate:
        rotations = _rotation_candidates(candidates)
        for candidate in rotations:
            t0 = time.time()
            try:
                code, final_url = _fetch_final(candidate, opener=opener)
            except urllib.error.HTTPError as e:
                if e.code in BLOCKED_STATUS_CODES:
                    continue
                continue
            except Exception:
                continue
            final_base = _base_of(final_url)
            if auto_update:
                mirrors = site_info.get("known_mirrors", [])
                additions = [m for m in (active_url, _base_of(candidate))
                             if m and m not in mirrors and m != final_base]
                update_site_registry(site_name, {
                    "active_base_url": final_base,
                    "known_mirrors": additions,
                    "status": "active",
                    "last_rotated_at": time.strftime(
                        "%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                })
            return {
                "site": site_name,
                "status": "rotated",
                "status_code": code,
                "candidate_tested": candidate,
                "final_base_url": final_base,
                "rotation_detected": True,
                "latency_sec": round(time.time() - t0, 2),
            }

    if auto_update:
        update_site_registry(site_name, {"status": "down"})

    return {
        "site": site_name,
        "status": "down",
        "error": "All candidates failed",
        "tested_candidates": candidates,
    }


def probe_all_sites(opener=None) -> list[dict]:
    """Probes all configured sites and returns audit summary."""
    reg = load_registry()
    results = []
    for site_name in sorted(reg.get("sites", {}).keys()):
        res = probe_site(site_name, auto_update=True, opener=opener)
        results.append(res)
    return results


_ICONS = {"active": "OK ", "rotated": "ROT", "blocked": "BLK",
          "down": "OFF", "unknown": " ? "}

if __name__ == "__main__":
    print("=" * 70)
    print(" Radd-Stream Fleet Domain Health, Auto-Discovery & Rotation Prober")
    print("=" * 70)
    sites = sys.argv[1:] or None
    if sites:
        results = [probe_site(s) for s in sites]
    else:
        results = probe_all_sites()
    for r in results:
        icon = _ICONS.get(r.get("status"), "?")
        shift = " (redirect-shifted)" if r.get("domain_shifted") else ""
        shift += " (TLD rotation)" if r.get("rotation_detected") else ""
        code = r.get("status_code", "ERR")
        url = r.get("final_base_url") or r.get("candidate_tested") or "N/A"
        lat = f"{r.get('latency_sec', 0.0)}s"
        print(f" [{icon}] {r['site']:<16} | HTTP {str(code):<4} | {lat:<7} | {url}{shift}")
    print("=" * 70)
