#!/usr/bin/env python3
"""
site_scout.py — Automated scraper synthesis & reverse-engineering scout (Phase 1).

Implements docs/SITE_SCOUT_SPEC.md Stages 1-5 as a real, importable CLI tool:

  Stage 1  Recon & CMS fingerprinting  (robots.txt, four sitemap paths,
           /wp-json/wp/v2/posts, /feed)
  Stage 2  Semantic DOM archaeology    (stdlib html.parser over 10-20 samples:
           title+year, poster/backdrop filtering, attribute vocabulary clustering)
  Stage 3  Link classification          (hrefs from candidate download containers
           classified direct | bridge | embed | unknown against domain_registry.json)
  Stage 4  Blueprint                    (site_blueprint.json, spec section 4 shape,
           plus scraped_at, sample_urls and per-field confidence)
  Stage 5  Scaffolding                   (hand blueprint to the local disciple model,
           then run a stdlib-compliance check + py_compile gate before writing an
           importer)

HARD LIMITS (spec section 4 item 1 mitigation is explicitly OUT of scope):
  * No Cloudflare / Turnstile / DDoS-Guard JS challenge bypass.
  * No headless-browser token hook.
  When a sample is a challenge interstitial the scout records
  ``blocked: challenge`` honestly and moves on — it never pretends to resolve it.

Python standard library ONLY. No pip, no third-party imports. The network layer is
injectable (an ``opener`` callable) so the whole thing runs offline under test.

Usage:
    python3 -S Fast_Fetch/site_scout.py https://target-site.com [options]
"""

from __future__ import annotations

import argparse
import ast
import io
import json
import os
import py_compile
import re
import ssl
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

REGISTRY_PATH = BASE_DIR / "domain_registry.json"

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# ---------------------------------------------------------------------------
# Project path conventions (never hardcode a data path outside these helpers)
# ---------------------------------------------------------------------------

_SYSTEM_PATH_ROOTS = ("home", "root", "usr", "var", "etc", "opt", "srv", "mnt", "data", "Users", "private")


def project_data_dir() -> Path:
    """Where staging databases live: RADD_DATA_DIR, else the Oracle data dir, else BASE_DIR."""
    env = os.environ.get("RADD_DATA_DIR")
    if env:
        return Path(env)
    oracle = Path("/home/ubuntu/radd-stream-data")
    if oracle.exists():
        return oracle
    return BASE_DIR


# ---------------------------------------------------------------------------
# Vocabularies (spec Stage 2 attribute matrix + Stage 3 classification + images)
# ---------------------------------------------------------------------------

SITEMAP_PATHS = (
    "/sitemap_index.xml",
    "/sitemap.xml",
    "/post-sitemap.xml",
    "/sitemap-index.xml",
)

RESOLUTION_TOKENS = ("480p", "720p", "1080p", "2160p", "4k", "uhd", "hdr")
LANGUAGE_TOKENS = (
    "hindi", "english", "tamil", "telugu", "bengali", "punjabi", "urdu",
    "korean", "japanese", "dual audio", "multi audio", "dubbed",
)
CODEC_TOKENS = ("x264", "x265", "hevc", "h264", "h265", "10bit", "8bit", "avc")

HEADING_TAGS = ("h1", "h2", "h3", "h4")
VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}

DOWNLOAD_CLASS_TOKENS = (
    "download", "dl-", "-dl", "btn", "button", "mirror", "server",
    "get-link", "action-btn", "watch-now", "file-link",
)
DOWNLOAD_TEXT_TOKENS = (
    "download", "mirror", "server", "gdrive", "1080p", "720p", "480p",
    "2160p", "4k", "direct", "torrent", "watch online",
)

# Images that are never a poster/backdrop (logos, badges, ad banners, icons...).
BAD_IMAGE_TOKENS = (
    "logo", "icon", "favicon", "avatar", "badge", "banner", "ads", "advert",
    "emoji", "sprite", "spacer", "placeholder", "loading", "brand", "watermark",
    "smiley", "cookie", "social",
)

# Known hoster registry (AGENTS.md section 4). ``domain_registry.json`` currently
# lists origin SITES, not hosters; the classifier merges this default table with any
# ``hosters``/``link_kinds`` section the registry file may add later.
DEFAULT_HOSTER_KINDS = (
    # --- direct cloud hosts ---
    ("pixeldrain.com", "direct"),
    ("drive.google.com", "direct"),
    ("docs.google.com", "direct"),
    ("r2.dev", "direct"),
    ("r2.cloudflarestorage.com", "direct"),
    ("gofile.io", "direct"),
    ("video-downloads.googleusercontent.com", "direct"),
    ("firebasestorage.googleapis.com", "direct"),
    ("1fichier", "direct"),
    ("megaup", "direct"),
    ("vikingfile", "direct"),
    ("dropgalaxy", "direct"),
    # --- bridge / shortener networks ---
    ("hubcloud", "bridge"),
    ("fastilinks", "bridge"),
    ("wlinksi", "bridge"),
    ("mzgserver", "bridge"),
    ("nexdrive", "bridge"),
    ("mobilejsr", "bridge"),
    ("linkszilla", "bridge"),
    ("gdflix", "bridge"),
    ("direct-cloud", "bridge"),
    ("greenmotors", "bridge"),
    ("10moviesz", "bridge"),
    ("vegadrive", "bridge"),
    ("filepress", "bridge"),
    ("filebee", "bridge"),
    ("gamerxyt", "bridge"),
    ("hblinks", "bridge"),
    ("hubdrive", "bridge"),
    # --- stream embeds ---
    ("streamtape", "embed"),
    ("vidhide", "embed"),
    ("1xplayer", "embed"),
    ("vcloud", "embed"),
    ("fastdl", "embed"),
    ("voe.sx", "embed"),
    ("dood", "embed"),
    ("vidsrc", "embed"),
    ("viduo", "embed"),
    ("autoembed", "embed"),
    ("filemoon", "embed"),
    ("uprot", "embed"),
)

# Cloudflare / DDoS-Guard / Turnstile interstitial markers (detection only, never bypassed).
CHALLENGE_MARKERS = (
    "cf-chl", "cf_chl", "challenge-platform", "__cf_chl",
    "checking your browser", "just a moment", "verify you are human",
    "ddos-guard", "turnstile", "cf-turnstile", "captcha-needlogin",
    "attack protection mode",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# HTTP layer (injectable opener so the whole scout runs offline under test)
# ---------------------------------------------------------------------------

def _default_opener(ssl_ctx: ssl.SSLContext):
    def _open(request: urllib.request.Request, timeout: float):
        return urllib.request.urlopen(request, timeout=timeout, context=ssl_ctx)
    return _open


class FetchResult:
    __slots__ = ("status", "url", "text", "headers")

    def __init__(self, status: int, url: str, text: str, headers: dict):
        self.status = status
        self.url = url
        self.text = text
        self.headers = headers


class SiteScout:
    """Drives stages 1-5 against a single target site. Network is injectable."""

    def __init__(
        self,
        base_url: str,
        *,
        opener=None,
        retries: int = 2,
        timeout: int = 15,
        ssl_ctx: ssl.SSLContext | None = None,
        registry: dict | None = None,
        max_samples: int = 20,
        sleep=lambda s: None,
    ):
        parsed = urllib.parse.urlparse(base_url if "://" in base_url else "https://" + base_url)
        if not parsed.netloc:
            raise ValueError(f"site_scout needs an absolute http(s) URL, got {base_url!r}")
        self.scheme = parsed.scheme or "https"
        self.host = parsed.netloc
        self.base_url = f"{self.scheme}://{parsed.netloc}"
        self.retries = max(1, int(retries))
        self.timeout = timeout
        self.ssl_ctx = ssl_ctx or _make_ssl_ctx()
        self._opener = opener or _default_opener(self.ssl_ctx)
        self.registry = registry if registry is not None else load_registry()
        self.kinds = build_kinds_map(self.registry)
        self.max_samples = max_samples
        self._sleep = sleep
        # artifacts captured during stages, reused by later stages
        self._wp_posts: list = []
        self._sitemap_xml: str = ""
        self._homepage_html: str = ""

    # ---- low level fetch -------------------------------------------------
    def _headers(self, accept: str = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"):
        return {
            "User-Agent": BROWSER_UA,
            "Accept": accept,
            "Accept-Language": "en-US,en;q=0.9",
        }

    def fetch(self, url: str, *, accept: str | None = None) -> FetchResult:
        last_status, last_text = 0, ""
        for attempt in range(self.retries):
            req = urllib.request.Request(url, headers=self._headers(accept or "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"))
            try:
                resp = self._opener(req, self.timeout)
                try:
                    status = getattr(resp, "status", None) or resp.getcode()
                    raw = resp.read()
                    final_url = resp.geturl() if hasattr(resp, "geturl") else url
                    headers_obj = getattr(resp, "headers", None)
                    headers = {}
                    if headers_obj is not None:
                        for key in ("Content-Type", "X-WP-Total", "X-WP-TotalPages"):
                            val = headers_obj.get(key) if hasattr(headers_obj, "get") else None
                            if val is not None:
                                headers[key] = val
                finally:
                    close = getattr(resp, "close", None)
                    if callable(close):
                        close()
                text = raw.decode("utf-8", errors="replace") if isinstance(raw, (bytes, bytearray)) else str(raw)
                return FetchResult(status, final_url, text, headers)
            except urllib.error.HTTPError as exc:  # 4xx/5xx is an answer, not a retry
                body = ""
                try:
                    body = exc.read().decode("utf-8", errors="replace")
                except Exception:
                    body = ""
                return FetchResult(exc.code, url, body, dict(getattr(exc, "headers", {}) or {}))
            except Exception:
                last_status, last_text = 0, ""
                if attempt < self.retries - 1:
                    self._sleep(0.5 * (attempt + 1))
        return FetchResult(last_status, url, last_text, {})

    def get_json(self, url: str):
        res = self.fetch(url, accept="application/json")
        if res.status != 200 or not res.text:
            return res.status, None, res
        try:
            return res.status, json.loads(res.text), res
        except Exception:
            return res.status, None, res

    # ---- Stage 1: recon & CMS fingerprinting -----------------------------
    def stage1_recon(self) -> dict:
        recon = {
            "robots": None,
            "sitemaps": {},
            "sitemap_url": None,
            "cms": None,
            "rest_api": {"usable": False, "url": None, "total_posts": None},
            "feed": {"usable": False, "url": None},
            "challenge": False,
        }

        robots = self.fetch(self.base_url + "/robots.txt", accept="text/plain")
        if robots.status == 200 and robots.text:
            sitemap_lines = [
                ln.split(":", 1)[1].strip()
                for ln in robots.text.splitlines()
                if ln.strip().lower().startswith("sitemap:")
            ]
            recon["robots"] = {
                "found": True,
                "declared_sitemaps": sitemap_lines,
            }

        for path in SITEMAP_PATHS:
            res = self.fetch(self.base_url + path, accept="application/xml")
            looks_xml = res.status == 200 and ("<urlset" in res.text or "<sitemapindex" in res.text or "<url>" in res.text)
            recon["sitemaps"][path] = {"status": res.status, "is_sitemap": bool(looks_xml)}
            if looks_xml and recon["sitemap_url"] is None:
                recon["sitemap_url"] = res.url
                self._sitemap_xml = res.text

        # If a sitemap is an index, resolve the first post-sitemap sub-sitemap.
        if recon["sitemap_url"] and "<sitemapindex" in self._sitemap_xml:
            for loc in re.findall(r"<loc>(https?://[^<]+)</loc>", self._sitemap_xml):
                if "post" in loc.lower() or "title" in loc.lower():
                    recon["sitemap_url"] = loc.strip()
                    sub = self.fetch(loc.strip())
                    if sub.status == 200:
                        self._sitemap_xml = sub.text
                    break

        wp = self.get_json(self.base_url + "/wp-json/wp/v2/posts?per_page=1")
        if wp[0] == 200 and isinstance(wp[1], list):
            recon["cms"] = "wordpress"
            total_hdr = wp[2].headers.get("X-WP-Total")
            recon["rest_api"] = {
                "usable": True,
                "url": self.base_url + "/wp-json/wp/v2/posts",
                "total_posts": int(total_hdr) if (total_hdr and str(total_hdr).isdigit()) else None,
            }

        feed = self.fetch(self.base_url + "/feed", accept="application/rss+xml")
        if feed.status == 200 and ("<rss" in feed.text or "<feed" in feed.text or "<item>" in feed.text):
            recon["feed"] = {"usable": True, "url": self.base_url + "/feed"}

        if is_challenge_interstitial(feed.text or "") or is_challenge_interstitial(robots.text or ""):
            recon["challenge"] = True

        home = self.fetch(self.base_url)
        self._homepage_html = home.text if home.status == 200 else ""
        if is_challenge_interstitial(self._homepage_html):
            recon["challenge"] = True

        return recon

    # ---- sample selection ------------------------------------------------
    def collect_sample_urls(self, recon: dict) -> list:
        urls: list = []
        seen = set()

        def push(u: str):
            u = u.split("#", 1)[0].strip()
            if not u:
                return
            p = urllib.parse.urlparse(u)
            if p.netloc and p.netloc != self.host:
                return
            low = u.lower()
            if any(seg in low for seg in ("/category/", "/tag/", "/author/", "/page/", "/feed", ".xml", ".css", ".js")):
                return
            if p.path in ("", "/"):
                return
            if u in seen:
                return
            seen.add(u)
            urls.append(u if u.startswith("http") else self.base_url + u)

        if recon["rest_api"]["usable"]:
            status, data, _ = self.get_json(recon["rest_api"]["url"] + "?per_page=%d" % self.max_samples)
            if status == 200 and isinstance(data, list):
                self._wp_posts = data
                for item in data:
                    if isinstance(item, dict) and item.get("link"):
                        push(item["link"])

        if not urls and self._sitemap_xml:
            for loc in re.findall(r"<loc>(https?://[^<]+)</loc>", self._sitemap_xml):
                push(loc.strip())
                if len(urls) >= self.max_samples:
                    break

        if not urls and self._homepage_html:
            digest = PageDigest()
            try:
                digest.feed(self._homepage_html)
            except Exception:
                pass
            for a in digest.anchors:
                push(a["href"])
                if len(urls) >= self.max_samples:
                    break

        return urls[: max(10, self.max_samples)]

    # ---- Stage 2 + 3: per-sample DOM archaeology + link classification ---
    def analyze_samples(self, sample_urls: list) -> dict:
        pages = []
        blocked = []
        for u in sample_urls:
            res = self.fetch(u)
            if res.status != 200 or not res.text:
                continue
            if is_challenge_interstitial(res.text):
                blocked.append({"url": u, "status": "blocked: challenge"})
                continue
            digest = PageDigest()
            try:
                digest.feed(res.text)
            except Exception:
                continue
            pages.append({"url": res.url, "digest": digest})
        return {"pages": pages, "blocked": blocked}

    def derive_title_regex(self, pages: list, site_name: str) -> dict:
        bracket_count = 0
        bare_count = 0
        matched = 0
        for pg in pages:
            raw = pick_raw_title(pg["digest"], site_name)
            if not raw:
                continue
            ym = re.search(r"[\(\[]\s*((?:19|20)\d{2})\s*[\)\]]", raw)
            if ym:
                matched += 1
                bracket_count += 1
                continue
            ym2 = re.search(r"(?:^|\s|\-|:)((?:19|20)\d{2})(?:\s|$)", raw)
            if ym2:
                matched += 1
                bare_count += 1
        total = len(pages)
        if matched == 0:
            regex = r"(?P<title>.+?)\s*[\(\[]\s*(?P<year>(?:19|20)\d{2})\s*[\)\]]"
            conf = 0.0
        elif bracket_count >= bare_count:
            regex = r"(?P<title>.+?)\s*[\(\[]\s*(?P<year>(?:19|20)\d{2})\s*[\)\]]"
        else:
            regex = r"(?P<title>.+?)\s*[^\w]?\s*(?P<year>(?:19|20)\d{2})"
            conf = 0.0
        conf = round(matched / total, 2) if total else 0.0
        return {"title_regex": regex, "confidence": conf}

    def derive_poster(self, pages: list) -> dict:
        best = None
        best_score = -1
        poster_pages = 0
        for pg in pages:
            d = pg["digest"]
            page_candidates = []
            for img in d.images:
                if is_bad_image(img):
                    continue
                if not img["src"]:
                    continue
                score = score_image(img)
                page_candidates.append((score, img["src"]))
            og = (d.meta.get("og:image") or "").strip()
            if og and not is_bad_image({"src": og, "class": "", "alt": ""}):
                page_candidates.append((500_000, og))
            if page_candidates:
                poster_pages += 1
                top_score, top_src = max(page_candidates, key=lambda t: t[0])
                if top_score > best_score:
                    best_score, best = top_score, top_src
        selector = "meta[property=\"og:image\"]"
        joined_html = " ".join(pg["digest"].raw_join() for pg in pages) if pages else ""
        if "post-thumbnail" in joined_html:
            selector = "article .post-thumbnail img"
        elif "wp-post-image" in joined_html:
            selector = ".wp-post-image"
        elif "entry-content" in joined_html:
            selector = ".entry-content img"
        total = len(pages)
        return {
            "poster_selector": selector,
            "poster_example": best,
            "confidence": round(poster_pages / total, 2) if total else 0.0,
        }

    def derive_attributes(self, pages: list) -> dict:
        counts = {}
        for pg in pages:
            d = pg["digest"]
            blob = " ".join(
                [d.title or ""] + [t for _, t in d.headings] + [a["text"] for a in d.anchors] +
                [v for v in d.meta.values() if v]
            ).lower()
            found = set()
            for tok in RESOLUTION_TOKENS + LANGUAGE_TOKENS + CODEC_TOKENS:
                pat = r"\b" + re.escape(tok) + r"\b" if " " not in tok else re.escape(tok)
                if re.search(pat, blob):
                    found.add(tok)
            for tok in found:
                counts[tok] = counts.get(tok, 0) + 1

        def bucket(tokens):
            return sorted([t for t in tokens if counts.get(t, 0) >= 2], key=lambda x: (-counts[x], x))

        res = bucket(RESOLUTION_TOKENS)
        langs = bucket(LANGUAGE_TOKENS)
        codecs = bucket(CODEC_TOKENS)
        any_attr = bool(res or langs or codecs)
        return {
            "resolutions": res,
            "languages": langs,
            "codecs": codecs,
            "confidence": 0.8 if any_attr else 0.0,
        }

    def classify_links(self, pages: list) -> dict:
        counts = {"direct": 0, "bridge": 0, "embed": 0, "unknown": 0}
        samples = {"direct": [], "bridge": [], "embed": [], "unknown": []}
        per_kind_hosts = {"direct": {}, "bridge": {}, "embed": {}, "unknown": {}}
        for pg in pages:
            d = pg["digest"]
            for a in d.anchors:
                if not a["in_container"]:
                    continue
                href = absolute(a["href"], self.base_url) if a["href"] else ""
                if not href or href.startswith(("javascript:", "mailto:", "#")):
                    continue
                kind = classify_href(href, self.kinds)
                counts[kind] += 1
                if len(samples[kind]) < 8:
                    samples[kind].append(href)
                host = urllib.parse.urlparse(href).netloc.lower()
                per_kind_hosts[kind][host] = per_kind_hosts[kind].get(host, 0) + 1

        link_patterns = []
        for kind in ("direct", "bridge", "embed"):
            if not per_kind_hosts[kind]:
                continue
            top_host = max(per_kind_hosts[kind].items(), key=lambda kv: kv[1])[0]
            link_patterns.append({"kind": kind, "regex": host_to_pattern(top_host, self.kinds)})
        return {"counts": counts, "samples": samples, "link_patterns": link_patterns}

    # ---- Stage 4: blueprint ---------------------------------------------
    def build_blueprint(self, target_url: str | None = None) -> dict:
        target_url = target_url or self.base_url
        recon = self.stage1_recon()
        samples = self.collect_sample_urls(recon)
        analysis = self.analyze_samples(samples)
        pages = analysis["pages"]
        site_name = derive_site_name(self.host)

        title_info = self.derive_title_regex(pages, site_name)
        poster_info = self.derive_poster(pages)
        attr_info = self.derive_attributes(pages)
        link_info = self.classify_links(pages)

        link_conf = 0.0
        total_links = sum(link_info["counts"].values())
        if total_links:
            link_conf = round((link_info["counts"]["direct"] + link_info["counts"]["bridge"] + link_info["counts"]["embed"]) / total_links, 2)

        blueprint = {
            # --- exact spec section 4 shape ---
            "site_name": site_name,
            "base_url": self.base_url,
            "cms": recon["cms"] or "unknown",
            "sitemap_url": recon["sitemap_url"],
            "title_regex": title_info["title_regex"],
            "poster_selector": poster_info["poster_selector"],
            "link_patterns": link_info["link_patterns"],
            # --- scout additions ---
            "scraped_at": _utc_now(),
            "target_url": target_url,
            "sample_urls": [pg["url"] for pg in pages],
            "blocked_samples": analysis["blocked"],
            "rest_api": recon["rest_api"],
            "data_source": "wp_rest_api" if recon["rest_api"]["usable"] else "html_scrape",
            "attributes": {
                "resolutions": attr_info["resolutions"],
                "languages": attr_info["languages"],
                "codecs": attr_info["codecs"],
            },
            "poster_example": poster_info["poster_example"],
            "link_counts": link_info["counts"],
            "confidence": {
                "title": title_info["confidence"],
                "poster": poster_info["confidence"],
                "attributes": attr_info["confidence"],
                "links": link_conf,
                "overall": round(
                    (title_info["confidence"] + poster_info["confidence"] + attr_info["confidence"] + link_conf) / 4.0, 2
                ) if pages else 0.0,
            },
            "notes": [
                "spec section 4 item 1 (Cloudflare/Turnstile/DDoS-Guard bypass + headless token hook) is intentionally NOT implemented; challenge pages are reported as 'blocked: challenge'.",
            ],
        }
        if recon["cms"] == "wordpress" and recon["rest_api"]["usable"]:
            blueprint["notes"].append(
                "wp-json REST feed answered -> HTML scraping may be bypassed; consume /wp-json/wp/v2/posts directly (spec Stage 1 decision)."
            )
        if recon["challenge"] and not pages:
            blueprint["notes"].append("Site appears to sit behind a JS challenge; samples could not be analyzed.")
        return blueprint

    # ---- Stage 5: scaffold ----------------------------------------------
    def scaffold(self, blueprint: dict, *, draft_fn=None, out_dir: Path | None = None, write: bool = True) -> dict:
        """Hand blueprint to the local disciple, gate the draft, and (if it passes)
        write import_<site>.py. On rejection keep the draft as <site>.draft.py."""
        out_dir = Path(out_dir) if out_dir else BASE_DIR
        data_dir = project_data_dir()
        prompt = build_scaffold_prompt(blueprint, data_dir)

        if draft_fn is None:
            draft_fn = _disciple_draft
        raw = draft_fn(prompt)
        code = extract_python(raw)

        ok, reasons = check_stdlib_compliance(code, data_dir=data_dir)
        compiles, compile_err = compile_check(code)
        accepted = ok and compiles

        site = blueprint["site_name"]
        result = {
            "site_name": site,
            "accepted": accepted,
            "compliance_ok": ok,
            "compiles": compiles,
            "reasons": reasons + ([f"py_compile: {compile_err}"] if not compiles else []),
            "written": None,
            "draft_kept": None,
        }
        if not write:
            return result

        if accepted:
            target = out_dir / f"import_{site}.py"
            target.write_text(code, encoding="utf-8")
            result["written"] = str(target)
        else:
            draft = out_dir / f"{site}.draft.py"
            draft.write_text(code, encoding="utf-8")
            result["draft_kept"] = str(draft)
        return result


# ---------------------------------------------------------------------------
# HTML parser (stdlib html.parser only)
# ---------------------------------------------------------------------------

class PageDigest(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = None
        self._in_title = False
        self._title_buf = []
        self.headings = []          # (tag, text)
        self._head_buf = None
        self.meta = {}              # og:image, description, og:title ...
        self.images = []            # {src, alt, class, width, height}
        self.anchors = []           # {href, text, class, in_container}
        self._anchor = None
        self._stack = []            # [{tag, download}]
        self._raw_tokens = []

    def _cls(self, attrs: dict) -> str:
        return f"{attrs.get('class','')} {attrs.get('id','')}".lower()

    def _download_ctx(self) -> bool:
        return any(x["download"] for x in self._stack)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = self._cls(a)
        self._raw_tokens.append(tag)
        if cls.strip():
            self._raw_tokens.append(cls)
        if tag == "title" and not self._in_title:
            self._in_title = True
            self._title_buf = []
        if tag == "meta":
            key = (a.get("property") or a.get("name") or "").lower()
            if key:
                self.meta.setdefault(key, a.get("content", "") or "")
        if tag == "img":
            src = a.get("src") or a.get("data-src") or a.get("data-lazy-src") or ""
            self.images.append({
                "src": src, "alt": a.get("alt", "") or "", "class": cls,
                "width": a.get("width"), "height": a.get("height"),
            })
        download_el = tag in ("div", "section", "ul", "ol", "li", "p", "span", "table", "td", "tr") and \
            any(tok in cls for tok in DOWNLOAD_CLASS_TOKENS)
        if tag not in VOID_TAGS:
            self._stack.append({"tag": tag, "download": download_el})
        if tag in HEADING_TAGS and self._head_buf is None:
            self._head_buf = []
        if tag == "a":
            href = a.get("href") or ""
            self._anchor = {
                "href": href, "text": [], "class": cls,
                "in_container": self._download_ctx() or any(tok in cls for tok in DOWNLOAD_CLASS_TOKENS),
            }

    def handle_data(self, data):
        if self._in_title:
            self._title_buf.append(data)
        if self._head_buf is not None:
            self._head_buf.append(data)
        if self._anchor is not None:
            self._anchor["text"].append(data)

    def handle_endtag(self, tag):
        if tag == "title" and self._in_title:
            self._in_title = False
            self.title = " ".join("".join(self._title_buf).split()).strip()
        if tag in HEADING_TAGS and self._head_buf is not None:
            text = " ".join("".join(self._head_buf).split()).strip()
            if text:
                self.headings.append((tag, text))
            self._head_buf = None
        if tag == "a" and self._anchor is not None:
            text = " ".join("".join(self._anchor["text"]).split()).strip()
            in_container = self._anchor["in_container"] or _download_text(text)
            if self._anchor["href"]:
                self.anchors.append({
                    "href": self._anchor["href"], "text": text,
                    "class": self._anchor["class"], "in_container": in_container,
                })
            self._anchor = None
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i]["tag"] == tag:
                del self._stack[i:]
                break

    def raw_join(self) -> str:
        return " ".join(self._raw_tokens)


def _download_text(text: str) -> bool:
    t = (text or "").lower()
    return any(tok in t for tok in DOWNLOAD_TEXT_TOKENS)


# ---------------------------------------------------------------------------
# Free helper functions (unit-testable without network)
# ---------------------------------------------------------------------------

def _make_ssl_ctx() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def is_challenge_interstitial(html: str) -> bool:
    if not html:
        return False
    low = html.lower()
    return any(marker in low for marker in CHALLENGE_MARKERS)


def derive_site_name(host: str) -> str:
    h = host.split(":", 1)[0].lower()
    parts = [p for p in h.split(".") if p]
    if parts and parts[0] == "www":
        parts = parts[1:]
    if len(parts) > 2 and parts[0] in ("new1", "new2", "new3", "new8", "m1"):
        parts = parts[1:]
    if not parts:
        return "site"
    if len(parts) >= 2:
        stem = "".join(parts[:-1])
    else:
        stem = parts[0]
    stem = re.sub(r"[^a-z0-9]+", "_", stem).strip("_").lower()
    return stem or "site"


def pick_raw_title(digest: PageDigest, site_name: str) -> str | None:
    brand_noise = {site_name.lower().replace("_", ""), site_name.lower().replace("_", " ")}
    og = (digest.meta.get("og:title") or "").strip()
    if og and og.lower() not in brand_noise:
        return _strip_branding(og, site_name)
    for _tag, text in digest.headings:
        low = text.lower().strip()
        if not low or low in brand_noise or low.replace(" ", "") in brand_noise:
            continue
        return _strip_branding(text, site_name)
    if digest.title:
        cleaned = _strip_branding(digest.title, site_name)
        if cleaned.lower() not in brand_noise:
            return cleaned
    return None


def _strip_branding(text: str, site_name: str) -> str:
    pretty = site_name.replace("_", " ").title()
    out = text
    for sep in (" - ", " | ", " – ", " — "):
        for brand in (pretty, site_name):
            out = out.replace(brand + sep, sep).replace(sep + brand, sep)
    for part in re.split(r"(\s[-|–—]\s)", out):
        pass
    # keep the segment that looks most like a title (contains a year or is longest)
    segs = [s.strip() for s in re.split(r"\s[-|–—]\s", out) if s.strip()]
    if segs:
        for s in segs:
            if re.search(r"(19|20)\d{2}", s):
                return s
        return max(segs, key=len)
    return out.strip()


def is_bad_image(img: dict) -> bool:
    blob = " ".join([
        (img.get("src") or ""), (img.get("alt") or ""), (img.get("class") or "")
    ]).lower()
    return any(tok in blob for tok in BAD_IMAGE_TOKENS)


def score_image(img: dict) -> int:
    score = 1000
    try:
        w = int(re.sub(r"[^0-9]", "", str(img.get("width") or "")) or 0)
        h = int(re.sub(r"[^0-9]", "", str(img.get("height") or "")) or 0)
    except ValueError:
        w = h = 0
    if w and h:
        area = w * h
        if area < 90_000:  # smaller than ~300x300 -> likely icon/badge
            score = 0
        else:
            score = area
    src = (img.get("src") or "").lower()
    if any(tok in src for tok in ("poster", "thumb", "wp-content/uploads", ".jpg", ".jpeg", ".webp")):
        score += 100
    if re.search(r"[-_](150|100|50|64|32)x\1", src):  # wp thumbnail size suffix
        score = 0
    return score


def absolute(href: str, base_url: str) -> str:
    return urllib.parse.urljoin(base_url + "/", href)


def load_registry(path: Path | None = None) -> dict:
    p = Path(path) if path else REGISTRY_PATH
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"sites": {}, "hosters": {}}


def build_kinds_map(registry: dict) -> list:
    """Ordered list of (host_token, kind). Registry 'hosters'/'link_kinds' sections
    (if present) take precedence over the built-in defaults."""
    overrides = {}
    for section in ("hosters", "link_kinds"):
        sec = registry.get(section) if isinstance(registry, dict) else None
        if isinstance(sec, dict):
            for token, kind in sec.items():
                if kind in ("direct", "bridge", "embed"):
                    overrides[token.lower()] = kind
    kinds = list(DEFAULT_HOSTER_KINDS)
    merged = []
    for token, kind in overrides.items():
        merged.append((token, kind))
    merged.extend([kt for kt in kinds if kt[0] not in overrides])
    return merged


def classify_href(url: str, kinds: list) -> str:
    if not url:
        return "unknown"
    low = url.lower()
    host = urllib.parse.urlparse(low).netloc or low
    for token, kind in kinds:
        if token in host or token in low:
            return kind
    return "unknown"


def host_to_pattern(host: str, kinds: list) -> str:
    """Generalize a host like hubcloud.ist into https://hubcloud\\.[a-z]+/... and add
    a representative path token class for the kind."""
    if not host:
        return "https?://[^/\\s]+/[^\\s\"']+"
    parts = host.split(".")
    if len(parts) >= 2:
        stem = parts[0]
        tld = parts[-1]
        host_pat = re.escape(stem) + r"\.[a-z]+" if len(parts) == 2 else re.escape(host).replace("\\.", r"\.")
    else:
        host_pat = re.escape(host)
    kind = classify_href("https://" + host, kinds)
    path_pat = {
        "direct": r"/(?:u|d|api/file|drive|d/)?[A-Za-z0-9_\-]+",
        "bridge": r"/(?:drive|view|file|genxfm)?/?[A-Za-z0-9_\-]+",
        "embed": r"/(?:v|e|embed)?/?[A-Za-z0-9_\-]+",
    }.get(kind, r"/[^\s\"'<>]+")
    return f"https?://{host_pat}{path_pat}"


def extract_python(response: str) -> str:
    m = re.search(r"```(?:python)?\s*([\s\S]*?)```", response or "")
    if m:
        return m.group(1).strip()
    return (response or "").strip()


def build_scaffold_prompt(blueprint: dict, data_dir: Path) -> str:
    site = blueprint["site_name"]
    return (
        "Write a complete Python module named import_{site}.py for the radd-stream project.\n"
        "STRICT RULES: Python standard library ONLY (urllib.request, sqlite3, re, json, pathlib).\n"
        "NEVER import requests, bs4, BeautifulSoup, lxml, pyquery, or subprocess. No shell-outs.\n"
        "Write rows into an isolated STAGING database named {site}.db inside the project data dir "
        "({data_dir}); NEVER touch the production catalog fast_fetch.db.\n"
        "Create the standard staging tables: sitemap_cache, posts, releases, download_sources via "
        "import fast_fetch; use fast_fetch.save_scraped_data(...) and fast_fetch.generate_canonical_key.\n"
        "18+ titles are STORED with is_18_plus=1 (flag, never skip).\n"
        "Use a browser-like User-Agent, timeouts, bounded retries.\n"
        "Site blueprint JSON:\n{bp}\n"
    ).format(site=site, data_dir=data_dir, bp=json.dumps(blueprint, indent=2))


def _disciple_draft(prompt: str) -> str:
    import disciple
    return disciple.draft_code(prompt)


# --- stdlib compliance gate ------------------------------------------------

_LOCAL_MODULES = {"fast_fetch", "config", "disciple", "site_scout", "bridge_tracer", "tiers", "redact",
                  "domain_resolver", "link_health", "catalog_api", "catalog_v2", "release_descriptor"}

_FORBIDDEN_MODULES = {"requests", "bs4", "beautifulsoup4", "lxml", "pyquery", "subprocess", "httpx",
                      "aiohttp", "selenium", "playwright", "pandas", "numpy"}
_FORBIDDEN_BUILTINS = ("os.system", "os.popen", "eval(", "exec(", "subprocess.")


def _is_abs_fs_path(s: str) -> bool:
    if ":\\" in s or s.startswith("\\\\"):
        return True
    if s.startswith("/") and not s.startswith("//"):
        m = re.match(r"^/([A-Za-z0-9_\-]+)", s)
        return bool(m and m.group(1) in _SYSTEM_PATH_ROOTS)
    return False


def check_stdlib_compliance(code: str, *, data_dir: Path | None = None, extra_allowed_modules=()) -> tuple:
    """Reject a draft that violates stdlib-only / staging-isolation. Returns (ok, reasons)."""
    data_dir = Path(data_dir) if data_dir else project_data_dir()
    allowed_roots = [str(data_dir), str(BASE_DIR), str(BASE_DIR.parent), "/home/ubuntu/radd-stream-data", "/tmp"]
    allowed = set(_LOCAL_MODULES) | set(extra_allowed_modules)
    reasons = []

    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return False, [f"syntax error: {exc}"]

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in _FORBIDDEN_MODULES:
                    reasons.append(f"forbidden third-party import: {alias.name}")
                elif top not in sys.stdlib_module_names and top not in allowed:
                    reasons.append(f"non-stdlib import: {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                top = node.module.split(".")[0]
                if top in _FORBIDDEN_MODULES:
                    reasons.append(f"forbidden third-party import: {node.module}")
                elif top not in sys.stdlib_module_names and top not in allowed:
                    reasons.append(f"non-stdlib import: {node.module}")
        elif isinstance(node, ast.Attribute):
            try:
                full = ast.unparse(node)
            except Exception:
                full = ""
            if full.startswith(("subprocess.", "os.system", "os.popen")):
                reasons.append(f"shell-out disallowed: {full}")
        elif isinstance(node, ast.Call):
            try:
                fn = ast.unparse(node.func)
            except Exception:
                fn = ""
            if fn in ("eval", "exec"):
                reasons.append(f"unsafe call disallowed: {fn}()")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            val = node.value
            if "fast_fetch.db" in val:
                reasons.append("scaffold must not target the production catalog (fast_fetch.db)")
            if _is_abs_fs_path(val) and not any(val == r or val.startswith(r.rstrip("/") + "/") for r in allowed_roots):
                reasons.append(f"absolute path outside project data dir: {val}")

    deduped = []
    for r in reasons:
        if r not in deduped:
            deduped.append(r)
    return (len(deduped) == 0), deduped


def compile_check(code: str) -> tuple:
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as fh:
            fh.write(code)
            tmp = fh.name
        py_compile.compile(tmp, doraise=True)
        return True, ""
    except py_compile.PyCompileError as exc:
        return False, str(exc)
    except Exception as exc:
        return False, str(exc)
    finally:
        try:
            os.unlink(tmp)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def scout_site(url: str, *, opener=None, max_samples: int = 20, retries: int = 2, timeout: int = 15, registry: dict | None = None) -> dict:
    scout = SiteScout(url, opener=opener, max_samples=max_samples, retries=retries, timeout=timeout, registry=registry)
    return scout.build_blueprint(url)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog="site_scout.py",
        description="Phase 1 site scout: recon, DOM archaeology, link classification, blueprint, scaffold.",
    )
    parser.add_argument("url", help="Target site URL, e.g. https://target-site.com")
    parser.add_argument("--max-samples", type=int, default=20, help="Sample post pages to fetch (10-20 typical)")
    parser.add_argument("--timeout", type=int, default=15, help="Per-request timeout seconds")
    parser.add_argument("--retries", type=int, default=2, help="Bounded retry count per request")
    parser.add_argument("--out", default=str(BASE_DIR / "site_blueprint.json"), help="Blueprint JSON output path")
    parser.add_argument("--scaffold", action="store_true", help="Run Stage 5 (calls the local disciple model)")
    parser.add_argument("--scaffold-only-draft", action="store_true", help="Stage 5 but never write import_*.py")
    parser.add_argument("--registry", default=str(REGISTRY_PATH), help="Known hoster registry JSON path")
    parser.add_argument("--json", action="store_true", help="Print blueprint JSON to stdout")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    registry = load_registry(Path(args.registry))
    scout = SiteScout(args.url, max_samples=args.max_samples, retries=args.retries, timeout=args.timeout, registry=registry)
    blueprint = scout.build_blueprint(args.url)

    out_path = Path(args.out)
    out_path.write_text(json.dumps(blueprint, indent=2), encoding="utf-8")

    if args.json:
        print(json.dumps(blueprint, indent=2))
    else:
        print(f"[✓] Blueprint written to {out_path}")
        print(f"    site_name={blueprint['site_name']} cms={blueprint['cms']} "
              f"rest_api={blueprint['rest_api']['usable']} samples={len(blueprint['sample_urls'])} "
              f"blocked={len(blueprint['blocked_samples'])}")
        conf = blueprint["confidence"]
        print(f"    confidence title={conf['title']} poster={conf['poster']} attributes={conf['attributes']} links={conf['links']}")

    if args.scaffold:
        result = scout.scaffold(blueprint, write=not args.scaffold_only_draft)
        if result["accepted"]:
            print(f"[✓] Scaffold accepted -> {result['written']}")
        else:
            print(f"[!] Scaffold REJECTED: {result['reasons']}")
            if result["draft_kept"]:
                print(f"    draft kept at {result['draft_kept']}")
    return blueprint


if __name__ == "__main__":
    main()
