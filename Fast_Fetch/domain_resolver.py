"""
Domain Resolver & Auto-Discovery Engine for Radd-Stream — Session 106 rewrite.

One registry, one reader, one chain (design: hidden_files/domain-tracking-design-20261108.md).

The problem it solves: every site rotates its domain every few weeks (same slug,
new TLD, a numeric prefix, or a subdomain swap). The importers survived only
because urllib follows 301s from a stale base; when the old domain stops
redirecting, the importer silently gets 0 posts. This module makes the code
search, cheapest-first, before a crawl — and proves the candidate is the real
site (content verification), not a parked / hijacked / doorway copy.

Discovery chain (cheapest first, stop at the first content-verified hit):
  1. cached    — registry active_base_url, probe its own endpoint
  2. redirect  — same request; urllib follows 301/302, a different final host is a move
  3. mirrors   — registry known_mirrors, same probe
  4. bookmark  — the site's bookmark domain (a stable 301 anchor), follow its redirect
  5. github    — the two community domain lists (cached 1h, shared by all sites)
  6. tld       — slug + historical TLDs first, then <=12 generic TLDs, www variants,
                 site prefixes (1/new1/m1), numeric patterns (filmyzillaNN, newN.hdhub4u)
  7. sister    — same-slug hosts harvested from any page fetched in steps 1-6
  8. search    — one DuckDuckGo HTML query, probe <=3 slug-matching hosts
  9. telegram — t.me/s/<verified channel>, parse announced domains, probe them
  10. give up  — record status: down, keep the old rows, NEVER write a guessed domain

Verification (design §5): a bare HTTP 200 proves nothing. A candidate is
accepted only if its own endpoint proves it:
  wp_rest_api : /wp-json/wp/v2/posts?per_page=3 -> JSON list, >=1 post whose
                link host == candidate host, AND >=1 post title carries a
                movie/series quality marker (480p/720p/1080p/WEB-DL/...), AND
                no title is IPTV spam (a name-squatter on ssrmovies.vip passed
                the old host-only check with all-IPTV posts — 2026-11-08).
  xml_sitemap : /sitemap.xml (fallbacks /sitemap_index.xml, /post-sitemap.xml)
                -> <urlset>/<sitemapindex> with >=10 same-host <loc> entries
                (>=2 if a <sitemapindex>; a doorway serves exactly 1 loc).
  homepage    : / -> >=2,000 bytes, <title> contains the site slug,
                >=3 internal post links, no parked markers.
Reject immediately: final host lacks every site slug (hijack/doorway),
parked markers in the body, Cloudflare challenge (403/503 + "Just a moment")
-> "unverifiable", not dead (a different egress may get through).

Reactive, not a watcher: no polling loop. A crawl failure triggers
resolve_site() for that site only; a verified domain is cached 6h
(last_verified). Rate discipline: 0.2s between probes to one host, 8s
timeout per probe, 200KB read cap, one probe per candidate per run.

100% Python Standard Library. Zero external dependencies.
"""

import contextlib
import fcntl
import http.client
import json
import os
import re
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

# Chain budgets (design §3, §6).
PROBE_TIMEOUT = 8            # seconds per probe; the socket timeout bounds the fetch
READ_CAP = 200_000           # bytes read per response body
PROBE_DELAY = 0.2            # seconds between probes to the same host
VERIFY_TTL_SECONDS = 6 * 3600   # a verified domain is trusted this long within a sweep
GITHUB_CACHE_SECONDS = 3600     # the two GitHub JSONs are fetched at most once an hour
MAX_TLD_PROBES = 20
MAX_NUMERIC_PROBES = 24   # 24 covers filmyzilla 70..81 bare+www (live: 80) and hdhub4u new1..20 bare
MAX_SEARCH_PROBES = 3
MAX_SISTER_PROBES = 5
KNOWN_MIRRORS_CAP = 8

GENERIC_TLDS = ["com", "net", "org", "xyz", "top", "click", "lol", "buzz",
                "vip", "one", "im", "io"]

#: HTTP answers that mean "a server is there and refusing our client", not
#: "the domain died". A challenge/WAF must never retire a working domain.
#: (Phase-1 hardening, ported from feat/phase1-resolved-cache.) Main's
#: discovery chain already does the bounded TLD-rotation sweep the branch
#: added, via _tld_candidates + resolve_site, so only the blocked-vs-down
#: rule and the write hardening are ported — not the rotation sweep.
BLOCKED_STATUS_CODES = frozenset({401, 403, 405, 429})

GITHUB_LISTS = [
    ("saurabh", "https://raw.githubusercontent.com/SaurabhKaperwan/Utils/refs/heads/main/urls.json"),
    ("phisher", "https://raw.githubusercontent.com/phisher98/TVVVV/refs/heads/main/domains.json"),
]

PARKED_MARKERS = [
    "domain for sale", "buy this domain", "this domain is parked",
    "parked domain", "sedo", "afternic", "dan.com", "hugedomains",
    "bodis", "parkingcrew", "is for sale", "just a moment",
    "attention required", "verify you are human", "domain parking",
    "this domain has expired", "domain expired",
]

# A movie/series post title carries at least one of these. The wp-json proof
# requires >=1 of the first 3 posts to match, so a site whose front page is
# all IPTV spam (ssrmovies.vip, 2026-11-08) is rejected even though its link
# host matched. Kept deliberately broad: one marker anywhere in the title.
QUALITY_MARKERS = [
    "480p", "720p", "1080p", "2160p", "4k", "web-dl", "webdl", "webrip",
    "hdtv", "hdts", "bluray", "brrip", "bdrip", "x264", "x265", "hevc",
    "dvdrip", "camrip", "hdcam", "dual audio", "hindi dubbed",
    "season", "episode", "s01", "s02", "s03", "s04", "s05",
]

# Titles that prove the "site" is a squatter serving a different kind of
# content, not the movie catalog the slug names.
IPTV_SPAM_MARKERS = ["iptv", "magentatv"]

# In-process cache for the two GitHub lists: fetched at most once an hour,
# shared across every site in the same process (design §6).
_GITHUB_CACHE = {"fetched_at": 0.0, "lists": {}}


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _get_ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _host_of(url: str) -> str:
    return urllib.parse.urlparse(url).netloc.lower()


def _slugs_of(entry: dict, site_name: str) -> list:
    slugs = entry.get("slug_variants") or [site_name]
    return [str(s).lower() for s in slugs if s]


def _host_matches_slug(host: str, slugs: list) -> bool:
    host = host.lower()
    return any(slug in host for slug in slugs)


# ── registry ────────────────────────────────────────────────────────────────

def load_registry(registry_path: str | Path | None = None) -> dict:
    path = Path(registry_path) if registry_path else REGISTRY_PATH
    if not path.exists():
        return {"version": "2.0", "sites": {}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or not isinstance(data.get("sites"), dict):
            return {"version": "2.0", "sites": {}}
        return data
    except Exception:
        return {"version": "2.0", "sites": {}}


def save_registry(data: dict, registry_path: str | Path | None = None) -> None:
    """Atomic write: temp file in the target directory + fsync + os.replace.

    json.dump runs BEFORE the replace, so a serialisation crash — or a
    cut mid-write — leaves the previous good file untouched. The temp
    file is unlinked on failure. The registry is read by the running
    service, so a truncated file is a live defect, not a cosmetic one.
    """
    path = Path(registry_path) if registry_path else REGISTRY_PATH
    data["updated_at"] = _now_iso()
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=str(path.parent),
                prefix=path.name + ".", suffix=".tmp", delete=False) as fh:
            tmp = Path(fh.name)
            json.dump(data, fh, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        if tmp is not None:
            with contextlib.suppress(OSError):
                tmp.unlink()
        raise


@contextlib.contextmanager
def _registry_lock(registry_path: str | Path | None = None):
    """Advisory exclusive flock on a sidecar ``<registry>.lock`` file.

    Never locks the registry itself: the replace in save_registry swaps
    the inode, which silently detaches any lock held on it.
    """
    path = Path(registry_path) if registry_path else REGISTRY_PATH
    lock_path = Path(str(path) + ".lock")
    fh = open(lock_path, "w")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        fh.close()


def update_site_registry(site_name: str, changes: dict,
                         registry_path: str | Path | None = None) -> dict:
    """Reload under lock, merge ``changes`` into that site's record, atomic
    save. Returns the merged site record.

    This is the ONLY sanctioned mutation path for single-site updates:
    reload-after-lock means the snapshot a caller read before its network
    work can never be written back wholesale over another run's updates.
    ``known_mirrors`` merges set-wise with the update's entries first
    (newest first, matching the rest of this module); every other key
    overwrites; the merged mirror list is capped at KNOWN_MIRRORS_CAP.
    """
    with _registry_lock(registry_path):
        reg = load_registry(registry_path)
        sites = reg.setdefault("sites", {})
        site = sites.setdefault(site_name, {})
        site.setdefault("site_name", site_name)
        for key, value in changes.items():
            if key == "known_mirrors" and isinstance(value, list):
                merged = [m for m in value if m]
                for item in site.get("known_mirrors", []):
                    if item and item not in merged:
                        merged.append(item)
                site["known_mirrors"] = merged[:KNOWN_MIRRORS_CAP]
            else:
                site[key] = value
        save_registry(reg, registry_path)
        return site


def get_active_base_url(site_name: str, fallback_default: str | None = None,
                        registry_path: str | Path | None = None) -> str:
    """Returns the current verified active base URL for a given site from registry.

    Pure read, no network — this is the one-line pattern every importer uses
    at crawl start (the hindilinks4u/toonworld4all pattern). The hardcoded
    DEFAULT_BASE_URL is only the fallback when the registry has no entry.
    """
    reg = load_registry(registry_path)
    site_info = reg.get("sites", {}).get(site_name)
    if site_info and site_info.get("active_base_url"):
        return site_info["active_base_url"]
    return fallback_default or ""


# ── fetch ───────────────────────────────────────────────────────────────────

def fetch_url(url: str, timeout: int = PROBE_TIMEOUT,
              max_bytes: int = READ_CAP) -> tuple:
    """One GET. Returns (status, final_url, text, error).

    Follows redirects (urllib default). A truncated read still yields its
    partial body (this sandbox's egress proxy truncates reads — a partial
    4KB wp-json body parsed as valid JSON on 2026-11-08). An HTTPError
    returns its code and body, not an exception. A transport failure
    returns status 0 with the error string. No SIGALRM here: this is a
    library, and importers run it inside threads where signals are unsafe;
    the socket timeout bounds the fetch.
    """
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })
    t0 = time.time()
    try:
        try:
            with urllib.request.urlopen(req, timeout=timeout,
                                        context=_get_ssl_context()) as resp:
                raw = resp.read(max_bytes + 1)
                text = raw[:max_bytes].decode("utf-8", "ignore")
                return resp.status, resp.geturl(), text, None
        except http.client.IncompleteRead as e:
            partial = e.partial or b""
            text = partial[:max_bytes].decode("utf-8", "ignore")
            return 200, url, text, None
        except urllib.error.HTTPError as e:
            try:
                text = e.read(max_bytes).decode("utf-8", "ignore")
            except Exception:
                text = ""
            return e.code, e.geturl() if hasattr(e, "geturl") else url, text, None
        except Exception as e:
            return 0, url, "", f"{type(e).__name__}: {e}"
    finally:
        _ = time.time() - t0


# ── content verification (design §5) ────────────────────────────────────────

def _parked_reason(text: str) -> str | None:
    low = text.lower()
    for marker in PARKED_MARKERS:
        if marker in low:
            return f"parked-marker:{marker}"
    return None


def _wp_title(post: dict) -> str:
    title = post.get("title", "")
    if isinstance(title, dict):
        title = title.get("rendered", "")
    return re.sub(r"""<[^>]+>""", "", str(title or "")).strip()


def verify_candidate(entry: dict, candidate_base: str, status: int,
                     final_url: str, text: str) -> tuple:
    """Content verification for one probed candidate.

    Pure function (no I/O) so tests can drive it with fixtures.
    Returns (ok, reason, verified_by). verified_by is "wp-json" / "sitemap" /
    "homepage" on a pass, "" on a fail. A Cloudflare challenge is a fail
    with reason "cloudflare-challenge http403|503" — the caller records the
    site "unverifiable", not dead. A WAF refusal (401/403/405/429 without
    challenge markers) is a fail with reason "blocked httpNNN" — the caller
    reports the site "blocked" and never demotes it.
    """
    slugs = _slugs_of(entry, entry.get("site_name", ""))
    final_host = _host_of(final_url)
    cand_host = _host_of(candidate_base)
    if status == 0:
        return False, "no-response", ""
    if status in (403, 503) and (
            "just a moment" in text.lower() or "attention required" in text.lower()):
        return False, f"cloudflare-challenge http{status}", ""
    if status in BLOCKED_STATUS_CODES:
        return False, f"blocked http{status}", ""
    if status != 200:
        return False, f"http{status}", ""
    # Session 106 fix (live catch 2026-11-08): the final host must carry a
    # site slug NO MATTER how it was reached. The old check only fired when
    # the final host differed from the candidate host, so a DDG result on an
    # unrelated host (hdtvb -> www.geekextreme.com, a tech blog whose
    # sitemapindex passed the sitemap branch) verified as the site's new
    # home. A candidate base that never carried the slug can never verify.
    if not _host_matches_slug(final_host, slugs):
        return False, f"host-no-site-slug:{final_host}", ""
    parked = _parked_reason(text)
    if parked:
        return False, parked, ""

    api_type = entry.get("api_type") or "homepage"
    if api_type == "wp_rest_api":
        try:
            data = json.loads(text)
        except Exception:
            return False, "wp-json-not-json", ""
        if not isinstance(data, list) or not data:
            return False, "wp-json-empty", ""
        link = str((data[0] or {}).get("link", ""))
        link_host = _host_of(link)
        if link_host and link_host != final_host and link_host != cand_host:
            return False, f"wp-json-link-elsewhere:{link_host}", ""
        # Content-kind check (chain gap b, 2026-11-08): the titles must look
        # like the site's catalog, not a squatter's IPTV spam.
        titles = [_wp_title(p) for p in data[:3] if isinstance(p, dict)]
        lowered = [t.lower() for t in titles]
        if any(any(m in t for m in IPTV_SPAM_MARKERS) for t in lowered):
            return False, "wp-json-iptv-spam", ""
        if not any(any(m in t for m in QUALITY_MARKERS) for t in lowered):
            return False, "wp-json-no-quality-marker", ""
        return True, f"wp-json {len(data)} post(s), link host ok", "wp-json"
    if api_type == "xml_sitemap":
        if "<urlset" not in text and "<sitemapindex" not in text:
            return False, "not-a-sitemap", ""
        locs = re.findall(r"""<loc>(https?://[^<]+)</loc>""", text, flags=re.I)
        same = [loc for loc in locs if _host_of(loc) == final_host]
        if not same:
            return False, "sitemap-no-same-host-loc", ""
        is_index = "<sitemapindex" in text
        if len(same) < 10 and not (is_index and len(same) >= 2):
            return False, f"sitemap-too-thin:{len(same)}-locs", ""
        return True, f"sitemap {len(locs)} locs, {len(same)} same-host", "sitemap"
    # homepage / sveltekit: title carries the slug, >=3 internal links.
    if len(text) < 2000:
        return False, f"homepage-too-small:{len(text)}-bytes", ""
    title_m = re.search(r"""<title[^>]*>(.*?)</title>""", text, flags=re.I | re.S)
    title_txt = re.sub(r"""<[^>]+>""", "", title_m.group(1)).lower() if title_m else ""
    title_norm = title_txt.replace("-", "").replace(" ", "")
    slug_in_title = any(slug.replace("-", "") in title_norm for slug in slugs)
    internal = set(re.findall(
        r"""href=["'](https?://""" + re.escape(final_host) + r"""/[^"']+)["']""",
        text, flags=re.I))
    if len(internal) < 3:
        return False, f"homepage-too-thin internal-links={len(internal)}", ""
    if not slug_in_title and not any(slug in text.lower() for slug in slugs):
        return False, "homepage-no-site-name", ""
    return True, f"homepage title={title_txt[:50]!r} internal-links={len(internal)}", "homepage"


def _endpoint_urls(entry: dict, base: str) -> list:
    """The URLs that prove this site's endpoint, cheapest first."""
    base = base.rstrip("/")
    api_type = entry.get("api_type") or "homepage"
    if api_type == "wp_rest_api":
        endpoint = entry.get("api_endpoint") or "/wp-json/wp/v2/posts"
        return [base + endpoint.rstrip("/") + "?per_page=3"]
    if api_type == "xml_sitemap":
        first = entry.get("sitemap_endpoint") or "/sitemap.xml"
        urls = [base + first]
        for extra in ("/sitemap_index.xml", "/post-sitemap.xml"):
            if base + extra not in urls:
                urls.append(base + extra)
        return urls
    return [base + "/"]


def probe_endpoint(entry: dict, base: str, fetcher=None) -> dict:
    """Probe one candidate base via its endpoint. Returns a result dict."""
    fetch = fetcher or fetch_url
    t0 = time.time()
    for url in _endpoint_urls(entry, base):
        status, final_url, text, err = fetch(url)
        if err:
            return {"ok": False, "tried": base, "reason": err,
                    "secs": round(time.time() - t0, 2)}
        ok, reason, verified_by = verify_candidate(entry, base, status, final_url, text)
        if ok:
            final_base = f"{urllib.parse.urlparse(final_url).scheme}://{_host_of(final_url)}"
            return {"ok": True, "tried": base, "live": final_base,
                    "reason": reason, "verified_by": verified_by,
                    "redirected": _host_of(final_url) != _host_of(base),
                    "secs": round(time.time() - t0, 2)}
        # A 404 sitemap on the right host is a wrong path, not a dead site:
        # try the next sitemap variant before giving up on this candidate.
        if entry.get("api_type") == "xml_sitemap" and status == 404:
            continue
        return {"ok": False, "tried": base, "reason": reason,
                "secs": round(time.time() - t0, 2)}
    return {"ok": False, "tried": base, "reason": "all-sitemap-variants-failed",
            "secs": round(time.time() - t0, 2)}


# ── chain sources: GitHub lists, search, Telegram, sister harvest ──────────

def fetch_github_lists(fetcher=None) -> dict:
    """The two community domain lists, cached 1h and shared by all sites.

    Returns {name: {"data": dict} | {"error": str}}. A fetch failure is an
    error entry, never an exception — the chain just skips that list.
    """
    now = time.time()
    if _GITHUB_CACHE["lists"] and now - _GITHUB_CACHE["fetched_at"] < GITHUB_CACHE_SECONDS:
        return _GITHUB_CACHE["lists"]
    fetch = fetcher or fetch_url
    out = {}
    for name, url in GITHUB_LISTS:
        status, _final, text, err = fetch(url, timeout=10)
        if err or status != 200:
            out[name] = {"error": err or f"http{status}"}
            continue
        try:
            out[name] = {"data": json.loads(text)}
        except Exception as e:
            out[name] = {"error": f"bad-json:{e}"}
    _GITHUB_CACHE["fetched_at"] = now
    _GITHUB_CACHE["lists"] = out
    return out


def ddg_search(slug: str, fetcher=None) -> tuple:
    """One DuckDuckGo HTML query. Returns (hosts, note).

    Result URLs are wrapped in a ?uddg= redirect parameter; unquoting it
    gives the real destination. Only slug-matching hosts are returned — an
    unrelated result page (a blog writing about the site, a parked page)
    can never become a candidate. A blocked or failed fetch returns ([],
    reason) — "search unavailable", never "site dead". Falls back to the
    lite endpoint once.
    """
    fetch = fetcher or fetch_url
    query = urllib.parse.quote_plus(f"{slug} new domain official site")
    for endpoint in ("https://html.duckduckgo.com/html/?q=",
                     "https://lite.duckduckgo.com/lite/?q="):
        status, _final, text, err = fetch(endpoint + query, timeout=10)
        if err or status != 200:
            note = f"ddg-fetch-failed:{err or status}"
            continue
        low = text.lower()
        if "captcha" in low or "anomaly" in low or "just a moment" in low:
            note = "ddg-blocked"
            continue
        hosts = []
        for m in re.finditer(r"""href="[^"]*uddg=([^"&]+)""", text):
            try:
                real = urllib.parse.unquote(m.group(1))
            except Exception:
                continue
            host = _host_of(real)
            if host and host not in hosts:
                hosts.append(host)
        if not hosts:
            for m in re.finditer(r'''class="result__a"[^>]*href="([^"]+)"''', text):
                host = _host_of(urllib.parse.unquote(m.group(1)))
                if host and host not in hosts:
                    hosts.append(host)
        # Session 106 fix: slug-matching hosts ONLY (see verify_candidate
        # note above — the non-slug tail let an unrelated DDG result verify
        # as hdtvb's new home on the 2026-11-08 live run).
        ranked = [h for h in hosts if slug in h]
        return ranked[:6], f"ddg {len(hosts)} hosts ({len(ranked)} slug-matching)"
    return [], note


def telegram_candidates(entry: dict, fetcher=None) -> tuple:
    """Hosts announced on the site's verified Telegram channel, if any.

    Only channels listed in the registry are ever read — never a guessed
    channel name. An announced domain is a candidate, never a fact, until
    the content check passes. Returns (hosts, note).
    """
    fetch = fetcher or fetch_url
    channel = entry.get("telegram_channel")
    if not channel:
        return [], "no-known-channel"
    slugs = _slugs_of(entry, entry.get("site_name", ""))
    status, _final, text, err = fetch(f"https://t.me/s/{channel}", timeout=10,
                                      max_bytes=400_000)
    if err or status != 200:
        return [], f"telegram-fetch-failed:{err or status}"
    found = []
    for m in re.finditer(r"""https?://([\w\-.]+)""", text):
        host = m.group(1).lower()
        if _host_matches_slug(host, slugs) and host not in found:
            found.append(host)
    return found, f"t.me/s/{channel}"


def harvest_sister_hosts(entry: dict, pages: list) -> list:
    """Same-slug hosts linked from any page fetched during this chain run.

    pages is a list of (url, text) pairs the chain already fetched. Only
    hosts containing one of the site's slug variants count, and asset/CDN
    subdomains are excluded.
    """
    slugs = _slugs_of(entry, entry.get("site_name", ""))
    found = []
    for _url, text in pages:
        if not text:
            continue
        for m in re.finditer(r"""href=["'](https?://[^"'<>\s]+)["']""", text):
            host = _host_of(m.group(1))
            if not host or host in found:
                continue
            if not _host_matches_slug(host, slugs):
                continue
            if any(x in host for x in ("img.", "wp.", "cdn.", "static.", "api.")):
                continue
            found.append(host)
    return found


# ── the chain ───────────────────────────────────────────────────────────────

def _tld_candidates(entry: dict) -> list:
    """TLD-probe candidates: history first, then <=12 generic, www variants,
    site prefixes, in that order. Bounded by MAX_TLD_PROBES."""
    slugs = _slugs_of(entry, entry.get("site_name", ""))
    history = [str(t).lstrip(".") for t in (entry.get("tld_history") or [])]
    cands = []

    def add(url: str):
        if url not in cands:
            cands.append(url)

    for slug in slugs:
        for tld in history:
            add(f"https://{slug}.{tld}")
            add(f"https://www.{slug}.{tld}")  # chain gap (a): www variants
        for tld in GENERIC_TLDS:
            add(f"https://{slug}.{tld}")
            add(f"https://www.{slug}.{tld}")
    for prefix in (entry.get("prefixes") or []):
        if not prefix:
            continue
        for slug in slugs:
            for tld in history[:4]:
                add(f"https://{prefix}{slug}.{tld}")
                add(f"https://www.{prefix}{slug}.{tld}")
    return cands[:MAX_TLD_PROBES]


def _numeric_candidates(entry: dict) -> list:
    """Numeric-rotation candidates (filmyzillaNN.com, newN.hdhub4u.cl)."""
    pattern = entry.get("numeric_pattern") or {}
    stem = pattern.get("stem") or pattern.get("prefix") or ""
    host = pattern.get("host") or ""
    tld = pattern.get("tld") or ""
    span = pattern.get("range") or []
    if not stem or len(span) != 2:
        return []
    cands = []
    for n in range(int(span[0]), int(span[1]) + 1):
        if host:
            cands.append(f"https://{stem}{n}.{host}")
        elif tld:
            cands.append(f"https://{stem}{n}.{tld}")
            cands.append(f"https://www.{stem}{n}.{tld}")
    return cands[:MAX_NUMERIC_PROBES]


def _record_verified(reg: dict, site_name: str, entry: dict, hit: dict,
                     registry_path) -> str:
    """Write a verified domain back to the registry entry and save.

    Reloads under the registry lock: resolve_site() loads its snapshot
    before a long discovery chain, and a concurrent probe must not lose
    its updates to a stale write-back. ``reg``/``entry`` are the caller's
    snapshot (kept for signature compatibility); the write goes to the
    freshly loaded record, so the rotation history reflects the actual
    transition, not the snapshot's.
    """
    new_base = hit["live"]
    with _registry_lock(registry_path):
        fresh = load_registry(registry_path)
        fresh_entry = fresh.setdefault("sites", {}).setdefault(site_name, {})
        fresh_entry.setdefault("site_name", site_name)
        old_base = fresh_entry.get("active_base_url", "")
        fresh_entry["active_base_url"] = new_base
        fresh_entry["last_verified"] = _now_iso()
        fresh_entry["verified_by"] = hit.get("verified_by", "")
        fresh_entry["status"] = "active"
        fresh_entry["last_checked"] = fresh_entry["last_verified"]
        mirrors = fresh_entry.setdefault("known_mirrors", [])
        if new_base in mirrors:
            mirrors.remove(new_base)
        mirrors.insert(0, new_base)
        del mirrors[KNOWN_MIRRORS_CAP:]
        if old_base and old_base != new_base:
            history = fresh_entry.setdefault("rotation_history", [])
            history.append({"domain": old_base,
                            "seen_until": fresh_entry["last_verified"]})
            history.append({"domain": new_base,
                            "seen_from": fresh_entry["last_verified"]})
        save_registry(fresh, registry_path)
    return new_base


def _record_unresolved(reg: dict, entry: dict, status: str, registry_path) -> None:
    """Record a failed chain run. The active base is NEVER overwritten with
    a guess — it stays until a later run verifies a replacement.

    Reloads under the registry lock, same reason as _record_verified.
    """
    site_name = entry.get("site_name")
    if not site_name:
        return
    with _registry_lock(registry_path):
        fresh = load_registry(registry_path)
        fresh_entry = fresh.setdefault("sites", {}).setdefault(site_name, {})
        fresh_entry.setdefault("site_name", site_name)
        fresh_entry["status"] = status
        fresh_entry["last_checked"] = _now_iso()
        save_registry(fresh, registry_path)


def resolve_site(site_name: str, registry_path: str | Path | None = None,
                 fetcher=None) -> str:
    """Run the §3 discovery chain for one site; return the verified base or "".

    Reactive: call this when a crawl fails (0 posts / connection error) for
    the site. On success the registry is updated (active_base_url,
    last_verified, verified_by, known_mirrors, rotation_history, status)
    and the verified base is returned. On failure the registry records
    status "down" (or "unverifiable" when every candidate was Cloudflare-
    challenged) and "" is returned — the old base stays, never a guess.
    """
    fetch = fetcher or fetch_url
    reg = load_registry(registry_path)
    entry = reg.get("sites", {}).get(site_name)
    if not entry:
        return ""
    entry.setdefault("site_name", site_name)
    attempts = []
    seen_pages = []
    tried = set()
    cf_only = True  # stays True only if every failure was a CF challenge

    def try_probe(base: str, label: str):
        if not base or base in tried:
            return None
        tried.add(base)
        if attempts:
            time.sleep(PROBE_DELAY)
        result = probe_endpoint(entry, base, fetcher=fetch)
        result["method"] = label
        attempts.append(result)
        return result

    # 1. cached active base (redirect-following is inside the probe).
    hit = try_probe(entry.get("active_base_url", ""), "cached")
    if hit and hit["ok"]:
        return _record_verified(reg, site_name, entry, hit, registry_path)
    if hit:
        cf_only = cf_only and hit["reason"].startswith(("cloudflare-challenge", "blocked"))

    # 3. known mirrors.
    for mirror in list(entry.get("known_mirrors") or []):
        hit = try_probe(mirror, "mirror")
        if hit and hit["ok"]:
            return _record_verified(reg, site_name, entry, hit, registry_path)
        if hit:
            cf_only = cf_only and hit["reason"].startswith(("cloudflare-challenge", "blocked"))

    # 4. bookmark domain (stable 301 anchor).
    bookmark = entry.get("bookmark_domain")
    if bookmark:
        status, final_url, text, err = fetch(bookmark, timeout=PROBE_TIMEOUT)
        attempts.append({"method": "bookmark", "tried": bookmark, "ok": False,
                         "reason": err or f"final={final_url}", "secs": 0})
        if not err and status == 200:
            final_host = _host_of(final_url)
            if _host_matches_slug(final_host, _slugs_of(entry, site_name)):
                base = f"{urllib.parse.urlparse(final_url).scheme}://{final_host}"
                hit = try_probe(base, "bookmark-follow")
                if hit and hit["ok"]:
                    return _record_verified(reg, site_name, entry, hit, registry_path)
                if hit:
                    cf_only = cf_only and hit["reason"].startswith(("cloudflare-challenge", "blocked"))

    # 5. GitHub community lists (fetched once an hour, shared by all sites).
    github = fetch_github_lists(fetcher=fetch)
    for key in (entry.get("github_keys") or {}).values():
        for list_name in ("saurabh", "phisher"):
            data = (github.get(list_name) or {}).get("data") or {}
            hit_url = None
            for k, v in data.items():
                if str(k).lower() == str(key).lower():
                    hit_url = v
                    break
            if not hit_url:
                continue
            if isinstance(hit_url, dict):
                hit_url = hit_url.get("url") or hit_url.get("domain") or ""
            if not hit_url:
                continue
            if not str(hit_url).startswith("http"):
                hit_url = "https://" + str(hit_url)
            hit = try_probe(str(hit_url), f"github-{list_name}")
            if hit and hit["ok"]:
                return _record_verified(reg, site_name, entry, hit, registry_path)
            if hit:
                cf_only = cf_only and hit["reason"].startswith(("cloudflare-challenge", "blocked"))

    # 6. TLD probe (history first, then generic, www variants) + numeric.
    for cand in _tld_candidates(entry):
        hit = try_probe(cand, "tld-probe")
        if hit and hit["ok"]:
            return _record_verified(reg, site_name, entry, hit, registry_path)
        if hit:
            cf_only = cf_only and hit["reason"].startswith(("cloudflare-challenge", "blocked"))
    for cand in _numeric_candidates(entry):
        hit = try_probe(cand, "numeric-probe")
        if hit and hit["ok"]:
            return _record_verified(reg, site_name, entry, hit, registry_path)
        if hit:
            cf_only = cf_only and hit["reason"].startswith(("cloudflare-challenge", "blocked"))

    # 7. sister cross-links from pages fetched above. The probe bodies were
    # not retained (memory), so re-fetch the cached base's homepage once as
    # the harvest source when it answered at all.
    if entry.get("active_base_url"):
        status, _final, text, err = fetch(entry["active_base_url"], timeout=PROBE_TIMEOUT)
        if not err and status == 200:
            seen_pages.append((entry["active_base_url"], text))
    for host in harvest_sister_hosts(entry, seen_pages)[:MAX_SISTER_PROBES]:
        hit = try_probe(f"https://{host}", "sister")
        if hit and hit["ok"]:
            return _record_verified(reg, site_name, entry, hit, registry_path)
        if hit:
            cf_only = cf_only and hit["reason"].startswith(("cloudflare-challenge", "blocked"))

    # 8. DuckDuckGo search (last resort, one query).
    hosts, why = ddg_search(_slugs_of(entry, site_name)[0], fetcher=fetch)
    attempts.append({"method": "search-ddg", "tried": "ddg query", "ok": False,
                     "reason": why, "secs": 0})
    for host in hosts[:MAX_SEARCH_PROBES]:
        hit = try_probe(f"https://{host}", "search-ddg")
        if hit and hit["ok"]:
            return _record_verified(reg, site_name, entry, hit, registry_path)
        if hit:
            cf_only = cf_only and hit["reason"].startswith(("cloudflare-challenge", "blocked"))

    # 9. Telegram channel (verified channels only, from the registry).
    found, why = telegram_candidates(entry, fetcher=fetch)
    attempts.append({"method": "telegram", "tried": f"t.me/s/{entry.get('telegram_channel')}",
                     "ok": False, "reason": why, "secs": 0})
    for host in found:
        hit = try_probe(f"https://{host}", "telegram")
        if hit and hit["ok"]:
            return _record_verified(reg, site_name, entry, hit, registry_path)
        if hit:
            cf_only = cf_only and hit["reason"].startswith(("cloudflare-challenge", "blocked"))

    # 10. give up: record it, never write a guessed domain.
    status = "unverifiable" if (cf_only and attempts) else "down"
    _record_unresolved(reg, entry, status, registry_path)
    return ""


def resolve_if_dead(site_name: str, registry_path: str | Path | None = None,
                    fetcher=None) -> str:
    """After a sync that found 0 posts: probe the cached base once.

    A routine re-sync of a fully-synced site legitimately returns 0 new
    posts, so "0 posts" alone must NOT trigger the chain. This helper
    distinguishes the two cases: if the cached base still verifies, the
    site is fine and "" is returned (nothing new — no retry). If the
    cached base fails verification, the full chain runs and the verified
    base is returned (or "" when the site is down/unverifiable).
    Importers call this exactly when a sync returns 0, then retry the
    sync once with the returned base when it is non-empty.
    """
    reg = load_registry(registry_path)
    entry = reg.get("sites", {}).get(site_name)
    if not entry:
        return ""
    entry.setdefault("site_name", site_name)
    result = probe_endpoint(entry, entry.get("active_base_url", ""), fetcher=fetcher)
    if result["ok"]:
        return ""
    return resolve_site(site_name, registry_path=registry_path, fetcher=fetcher)


# ── probing (kept from the v1 module, now content-verified) ─────────────────

def probe_site(site_name: str, auto_update: bool = True,
               registry_path: str | Path | None = None, fetcher=None) -> dict:
    """
    Probes the active domain for a site, then its mirrors, with content
    verification (not a bare 200). Follows redirects; a different final
    host that passes verification is a move and updates the registry.
    Returns status dict with live URL, status code, and latency.
    This is the cheap probe (cached + mirrors only) — the full chain is
    resolve_site().
    """
    reg = load_registry(registry_path)
    site_info = reg.get("sites", {}).get(site_name)
    if not site_info:
        return {"site": site_name, "status": "unknown", "error": "Site not in registry"}

    site_info.setdefault("site_name", site_name)
    active_url = site_info.get("active_base_url", "")
    known_mirrors = site_info.get("known_mirrors", [active_url])
    candidates = [active_url] + [m for m in known_mirrors if m != active_url]
    blocked_seen = False

    for candidate in candidates:
        if not candidate:
            continue
        t0 = time.time()
        result = probe_endpoint(site_info, candidate, fetcher=fetcher)
        elapsed = time.time() - t0
        if not result["ok"]:
            if result["reason"].startswith("cloudflare-challenge"):
                if auto_update:
                    update_site_registry(site_name, {
                        "status": "unverifiable",
                        "last_checked": _now_iso(),
                    }, registry_path)
                return {"site": site_name, "status": "unverifiable",
                        "error": result["reason"], "tested_candidates": candidates}
            if (result["reason"].startswith("blocked")
                    and candidate == active_url):
                blocked_seen = True
            continue
        final_base = result["live"]
        domain_shifted = _host_of(final_base) != _host_of(active_url)
        if auto_update and (domain_shifted or final_base != active_url):
            now = _now_iso()
            update_site_registry(site_name, {
                "active_base_url": final_base,
                "last_verified": now,
                "verified_by": result.get("verified_by", ""),
                "status": "active",
                "last_checked": now,
                "known_mirrors": [final_base],
            }, registry_path)
        return {
            "site": site_name,
            "status": "active",
            "status_code": 200,
            "candidate_tested": candidate,
            "final_base_url": final_base,
            "domain_shifted": domain_shifted,
            "verified_by": result.get("verified_by", ""),
            "latency_sec": round(elapsed, 2),
        }

    if blocked_seen:
        # The active domain answered with a WAF refusal: the site is not
        # dead, its health is just unknown to this client. Report it and
        # touch nothing — a blocked probe must never demote a domain.
        return {
            "site": site_name,
            "status": "blocked",
            "error": "active domain refuses our client; health unknown, registry untouched",
            "tested_candidates": candidates,
        }

    if auto_update:
        update_site_registry(site_name, {
            "status": "down",
            "last_checked": _now_iso(),
        }, registry_path)

    return {
        "site": site_name,
        "status": "down",
        "error": "All candidates failed",
        "tested_candidates": candidates,
    }


def probe_all_sites(only_stale: bool = False,
                     registry_path: str | Path | None = None,
                     fetcher=None) -> list[dict]:
    """Probes all configured sites and returns audit summary.

    With only_stale=True (the §6 sweep rule) a site whose status is active
    and whose last_verified is younger than VERIFY_TTL_SECONDS is skipped
    — a sweep that finds nothing new still updates last_checked for the
    sites it did probe.
    """
    reg = load_registry(registry_path)
    results = []
    for site_name in sorted(reg.get("sites", {}).keys()):
        if only_stale:
            entry = reg["sites"][site_name]
            last = entry.get("last_verified") or ""
            if entry.get("status") == "active" and last:
                try:
                    age = time.time() - time.mktime(time.strptime(last, "%Y-%m-%dT%H:%M:%SZ"))
                except Exception:
                    age = VERIFY_TTL_SECONDS + 1
                if age < VERIFY_TTL_SECONDS:
                    results.append({"site": site_name, "status": "active",
                                    "skipped": True, "reason": "verified within TTL"})
                    continue
        results.append(probe_site(site_name, auto_update=True,
                                  registry_path=registry_path, fetcher=fetcher))
    return results


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "resolve" and len(args) > 1:
        for site in args[1:]:
            base = resolve_site(site)
            print(f"{site}: {'LIVE ' + base if base else 'UNRESOLVED (see registry status)'}")
    elif args and args[0] == "resolve-all":
        reg = load_registry()
        for site in sorted(reg.get("sites", {}).keys()):
            base = resolve_site(site)
            print(f"{site}: {'LIVE ' + base if base else 'UNRESOLVED (see registry status)'}")
    else:
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
