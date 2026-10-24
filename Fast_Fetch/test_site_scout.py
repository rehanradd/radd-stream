#!/usr/bin/env python3
"""
test_site_scout.py — Offline tests for site_scout.py (Phase 1) and bridge_tracer.py
(Phase 2). No network: every fetch is served from recorded HTML/JSON fixtures fed
through an injectable fake opener.

Run:  python3 -S Fast_Fetch/test_site_scout.py
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import site_scout
import bridge_tracer


# ---------------------------------------------------------------------------
# Fake network plumbing
# ---------------------------------------------------------------------------

class FakeHeaders:
    def __init__(self, d):
        self._d = {k.lower(): v for k, v in d.items()}

    def get(self, key, default=None):
        return self._d.get(key.lower(), default)


class FakeResponse:
    def __init__(self, status, url, body, headers=None):
        self.status = status
        self._url = url
        self._body = body.encode("utf-8") if isinstance(body, str) else body
        self.headers = FakeHeaders(headers or {})

    def read(self):
        return self._body

    def geturl(self):
        return self._url

    def close(self):
        pass


class FakeOpener:
    """Callable opener for SiteScout: FakeOpener(request, timeout) -> FakeResponse."""

    def __init__(self, routes):
        self.routes = routes  # list of (substring, status, body, headers)
        self.requested = []

    def _match(self, url):
        for sub, status, body, headers in self.routes:
            if sub in url:
                return status, body, headers
        return 404, "", {}

    def __call__(self, request, timeout):
        url = request.get_full_url() if hasattr(request, "get_full_url") else str(request)
        self.requested.append(url)
        status, body, headers = self._match(url)
        return FakeResponse(status, url, body, headers)


class FakeTracerOpener:
    """Opener-like object exposing .open(req, timeout) for BridgeTracer."""

    def __init__(self, routes):
        self.routes = routes  # list of (substring, status, body, headers)

    def _match(self, url):
        for sub, status, body, headers in self.routes:
            if sub in url:
                return status, body, headers
        return 200, "", {}

    def open(self, request, timeout=15):
        url = request.get_full_url() if hasattr(request, "get_full_url") else str(request)
        status, body, headers = self._match(url)
        return FakeResponse(status, url, body, headers)


# ---------------------------------------------------------------------------
# HTML fixtures
# ---------------------------------------------------------------------------

POST_HTML = """<html>
<head>
  <title>Vegamovies.to - Inception (2010) 1080p - Hindi English</title>
  <meta property="og:image" content="https://cdn.example/img/inception-poster-1000x1500.jpg">
  <meta name="description" content="Inception 2010 Dual Audio Hindi English 1080p x265">
</head>
<body>
  <div class="site-logo"><img src="https://cdn.example/img/logo-site.png" class="logo" width="80" height="80" alt="site logo"></div>
  <article class="post">
    <div class="post-thumbnail"><img src="https://cdn.example/img/inception-poster-1000x1500.jpg" class="wp-post-image" width="1000" height="1500" alt="Inception"></div>
    <h2 class="entry-title">Vegamovies.to - Inception (2010) 1080p</h2>
    <div class="download-links">
      <a class="dl-btn" href="https://hubcloud.ist/drive/ABC123">Download 1080p x265</a>
      <a href="https://pixeldrain.com/u/zz9k2">Mirror 720p</a>
      <a href="https://streamtape.com/v/QWE45r">Watch 480p</a>
      <a href="https://randomhoster.example/file/xyz">Other Link</a>
    </div>
    <a href="/about-us/">About</a>
    <img src="https://cdn.example/img/banner-ad.gif" class="ad-banner" width="728" height="90" alt="advertisement">
  </article>
</body></html>"""

SERIES_HTML = """<html>
<head>
  <title>Vegamovies.to - Dark (2017) Season 2 720p</title>
  <meta property="og:image" content="https://cdn.example/img/dark-poster-800x1200.jpg">
</head>
<body>
  <article class="post">
    <div class="post-thumbnail"><img src="https://cdn.example/img/dark-poster-800x1200.jpg" class="wp-post-image" width="800" height="1200"></div>
    <h2>Dark (2017) Season 2 720p</h2>
    <div class="download-links">
      <a href="https://hubcloud.ist/drive/DEF456">1080p x264</a>
      <a href="https://pixeldrain.com/u/aa11">480p</a>
    </div>
  </article>
</body></html>"""

CHALLENGE_HTML = """<html><head><title>Just a moment...</title></head>
<body><div class="cf-turnstile">Checking your browser before accessing this site.</div></body></html>"""

WP_POSTS = json.dumps([
    {"link": "https://vegamovies.to/inception-2010-1080p/", "slug": "inception-2010-1080p", "modified": "2026-01-01T00:00:00"},
    {"link": "https://vegamovies.to/dark-2017-season-2/", "slug": "dark-2017-season-2", "modified": "2026-01-02T00:00:00"},
])


def build_scroutes():
    return [
        ("/robots.txt", 200, "User-agent: *\nSitemap: https://vegamovies.to/sitemap_index.xml\n", {}),
        ("/sitemap_index.xml", 200,
         '<sitemapindex><sitemap><loc>https://vegamovies.to/post-sitemap.xml</loc></sitemap></sitemapindex>',
         {"Content-Type": "application/xml"}),
        ("/post-sitemap.xml", 200,
         '<urlset><url><loc>https://vegamovies.to/inception-2010-1080p/</loc></url>'
         '<url><loc>https://vegamovies.to/dark-2017-season-2/</loc></url></urlset>',
         {"Content-Type": "application/xml"}),
        ("/wp-json/wp/v2/posts?per_page=1", 200, "[]", {"Content-Type": "application/json", "X-WP-Total": "2"}),
        ("/wp-json/wp/v2/posts?per_page=20", 200, WP_POSTS, {"Content-Type": "application/json"}),
        ("/feed", 200, "<rss><channel><item/></channel></rss>", {"Content-Type": "application/rss+xml"}),
        ("/inception-2010-1080p/", 200, POST_HTML, {}),
        ("/dark-2017-season-2/", 200, SERIES_HTML, {}),
        ("https://vegamovies.to", 200, "<html><body>home</body></html>", {}),
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class ReconProbeTests(unittest.TestCase):
    def setUp(self):
        self.opener = FakeOpener(build_scroutes())
        self.scout = site_scout.SiteScout("https://vegamovies.to", opener=self.opener)

    def test_sitemap_and_robots_and_wpjson_are_probed(self):
        recon = self.scout.stage1_recon()
        self.assertTrue(recon["robots"]["found"])
        self.assertIn("https://vegamovies.to/sitemap_index.xml", recon["robots"]["declared_sitemaps"])
        # one of the four sitemap paths answered
        self.assertTrue(any(info["is_sitemap"] for info in recon["sitemaps"].values()))
        self.assertIsNotNone(recon["sitemap_url"])
        self.assertEqual(recon["cms"], "wordpress")
        self.assertTrue(recon["rest_api"]["usable"])
        self.assertEqual(recon["rest_api"]["total_posts"], 2)
        self.assertTrue(recon["feed"]["usable"])

    def test_wpjson_usable_marks_rest_bypass(self):
        recon = self.scout.stage1_recon()
        self.assertEqual(recon["cms"], "wordpress")
        self.assertTrue(recon["rest_api"]["usable"])

    def test_no_network_calls_beyond_fake_opener(self):
        self.scout.stage1_recon()
        self.assertTrue(all("vegamovies.to" in u for u in self.opener.requested))


class TitleYearExtractionTests(unittest.TestCase):
    def _digest(self, html):
        d = site_scout.PageDigest()
        d.feed(html)
        return d

    def test_branding_stripped_and_year_found(self):
        d = self._digest(POST_HTML)
        raw = site_scout.pick_raw_title(d, "vegamovies")
        self.assertIsNotNone(raw)
        self.assertIn("2010", raw)
        self.assertNotIn("Vegamovies.to", raw)

    def test_derive_title_regex_prefers_bracket_year(self):
        opener = FakeOpener(build_scroutes())
        scout = site_scout.SiteScout("https://vegamovies.to", opener=opener)
        scout.stage1_recon()
        pages = scout.analyze_samples(scout.collect_sample_urls(scout.stage1_recon()))["pages"]
        info = scout.derive_title_regex(pages, "vegamovies")
        self.assertIn("(?P<title>", info["title_regex"])
        self.assertIn("(?P<year>", info["title_regex"])
        self.assertGreater(info["confidence"], 0.0)


class PosterFilterTests(unittest.TestCase):
    def test_logo_and_ad_banner_are_rejected(self):
        logo = {"src": "https://x/logo-site.png", "class": "logo", "alt": "site logo"}
        banner = {"src": "https://x/banner-ad.gif", "class": "ad-banner", "alt": "advertisement"}
        poster = {"src": "https://x/inception-poster-1000x1500.jpg", "class": "wp-post-image", "alt": "Inception"}
        self.assertTrue(site_scout.is_bad_image(logo))
        self.assertTrue(site_scout.is_bad_image(banner))
        self.assertFalse(site_scout.is_bad_image(poster))

    def test_small_images_scored_out_by_area(self):
        tiny = {"src": "https://x/i.png", "width": "50", "height": "50"}
        big = {"src": "https://x/p.jpg", "width": "1000", "height": "1500"}
        self.assertEqual(site_scout.score_image(tiny), 0)
        self.assertGreater(site_scout.score_image(big), 100_000)

    def test_derive_poster_picks_the_real_poster(self):
        opener = FakeOpener(build_scroutes())
        scout = site_scout.SiteScout("https://vegamovies.to", opener=opener)
        pages = scout.analyze_samples(scout.collect_sample_urls(scout.stage1_recon()))["pages"]
        info = scout.derive_poster(pages)
        self.assertIsNotNone(info["poster_example"])
        self.assertIn("poster", info["poster_example"])
        self.assertIn("post-thumbnail", info["poster_selector"])
        self.assertGreater(info["confidence"], 0.0)


class LinkClassificationTests(unittest.TestCase):
    def setUp(self):
        self.kinds = site_scout.build_kinds_map(site_scout.load_registry())

    def test_registry_kinds(self):
        self.assertEqual(site_scout.classify_href("https://hubcloud.ist/drive/x", self.kinds), "bridge")
        self.assertEqual(site_scout.classify_href("https://pixeldrain.com/u/x", self.kinds), "direct")
        self.assertEqual(site_scout.classify_href("https://streamtape.com/v/x", self.kinds), "embed")
        self.assertEqual(site_scout.classify_href("https://totally-unknown-xyz.example/a", self.kinds), "unknown")

    def test_registry_hosters_section_overrides_defaults(self):
        reg = {"sites": {}, "hosters": {"hubcloud": "direct"}}
        kinds = site_scout.build_kinds_map(reg)
        self.assertEqual(site_scout.classify_href("https://hubcloud.ist/drive/x", kinds), "direct")

    def test_download_container_hrefs_are_classified(self):
        opener = FakeOpener(build_scroutes())
        scout = site_scout.SiteScout("https://vegamovies.to", opener=opener)
        pages = scout.analyze_samples(scout.collect_sample_urls(scout.stage1_recon()))["pages"]
        info = scout.classify_links(pages)
        self.assertGreaterEqual(info["counts"]["bridge"], 1)
        self.assertGreaterEqual(info["counts"]["direct"], 1)
        self.assertGreaterEqual(info["counts"]["embed"], 1)


class BlueprintShapeTests(unittest.TestCase):
    def test_blueprint_has_exact_spec_shape_plus_additions(self):
        opener = FakeOpener(build_scroutes())
        scout = site_scout.SiteScout("https://vegamovies.to", opener=opener)
        bp = scout.build_blueprint()
        # exact spec section 4 keys
        for key in ("site_name", "base_url", "cms", "sitemap_url", "title_regex", "poster_selector", "link_patterns"):
            self.assertIn(key, bp)
        self.assertIsInstance(bp["link_patterns"], list)
        for pat in bp["link_patterns"]:
            self.assertIn("kind", pat)
            self.assertIn("regex", pat)
            self.assertIn(pat["kind"], ("direct", "bridge", "embed"))
        # scout additions
        self.assertIn("scraped_at", bp)
        self.assertIn("sample_urls", bp)
        self.assertIn("confidence", bp)
        self.assertEqual(set(bp["confidence"].keys()), {"title", "poster", "attributes", "links", "overall"})
        self.assertEqual(bp["data_source"], "wp_rest_api")
        # valid json round-trip
        json.dumps(bp)


class ChallengeHonestyTests(unittest.TestCase):
    def test_challenge_page_is_reported_not_bypassed(self):
        routes = [
            ("/robots.txt", 404, "", {}),
            ("/sitemap_index.xml", 404, "", {}),
            ("/sitemap.xml", 404, "", {}),
            ("/post-sitemap.xml", 404, "", {}),
            ("/sitemap-index.xml", 404, "", {}),
            ("/wp-json/wp/v2/posts?per_page=1", 404, "", {}),
            ("/wp-json/wp/v2/posts?per_page=20", 404, "", {}),
            ("/feed", 404, "", {}),
            ("/locked-post/", 200, CHALLENGE_HTML, {}),
            ("https://walled.site", 200,
             '<html><body><a href="/locked-post/">read</a></body></html>', {}),
        ]
        opener = FakeOpener(routes)
        scout = site_scout.SiteScout("https://walled.site", opener=opener)
        bp = scout.build_blueprint()
        self.assertEqual(bp["sample_urls"], [])
        self.assertTrue(bp["blocked_samples"])
        self.assertEqual(bp["blocked_samples"][0]["status"], "blocked: challenge")
        self.assertEqual(bp["confidence"]["overall"], 0.0)
        # the scout never claimed a bypass
        self.assertTrue(any("bypass" in n or "challenge" in n for n in bp["notes"]))


class StdlibComplianceTests(unittest.TestCase):
    def setUp(self):
        self.data_dir = Path("/home/ubuntu/radd-stream-data")

    def test_requests_import_is_rejected(self):
        ok, reasons = site_scout.check_stdlib_compliance(
            "import requests\nprint(requests.get('http://x'))", data_dir=self.data_dir
        )
        self.assertFalse(ok)
        self.assertTrue(any("requests" in r for r in reasons))

    def test_bs4_and_lxml_and_subprocess_rejected(self):
        code = "from bs4 import BeautifulSoup\nimport lxml\nimport subprocess\n"
        ok, reasons = site_scout.check_stdlib_compliance(code, data_dir=self.data_dir)
        self.assertFalse(ok)
        joined = " ".join(reasons)
        for bad in ("bs4", "lxml", "subprocess"):
            self.assertIn(bad, joined)

    def test_production_catalog_path_rejected(self):
        code = "import sqlite3\np='/home/ubuntu/radd-stream-data/fast_fetch.db'\n"
        ok, reasons = site_scout.check_stdlib_compliance(code, data_dir=self.data_dir)
        self.assertFalse(ok)
        self.assertTrue(any("fast_fetch.db" in r for r in reasons))

    def test_absolute_path_outside_data_dir_rejected(self):
        code = "import sqlite3\np='/etc/passwd.db'\n"
        ok, reasons = site_scout.check_stdlib_compliance(code, data_dir=self.data_dir)
        self.assertFalse(ok)
        self.assertTrue(any("absolute path" in r for r in reasons))

    def test_clean_stdlib_draft_accepted(self):
        code = (
            "import urllib.request, sqlite3, json, re\n"
            "from pathlib import Path\n"
            "DB=Path('/home/ubuntu/radd-stream-data/vegamovies.db')\n"
            "print(DB)\n"
        )
        ok, reasons = site_scout.check_stdlib_compliance(code, data_dir=self.data_dir)
        self.assertTrue(ok, reasons)

    def test_compile_check_rejects_bad_syntax(self):
        ok, err = site_scout.compile_check("def broken(:\n  pass")
        self.assertFalse(ok)
        self.assertTrue(err)

    def test_scaffold_keeps_rejected_draft_and_writes_no_importer(self):
        bp = {"site_name": "vegamovies", "base_url": "https://vegamovies.to"}
        bad_draft = "```python\nimport requests\nrequests.get('https://x')\n```"
        with TemporaryDirectory() as td:
            result = site_scout.SiteScout("https://vegamovies.to", opener=FakeOpener([])).scaffold(
                bp, draft_fn=lambda prompt: bad_draft, out_dir=Path(td)
            )
            self.assertFalse(result["accepted"])
            self.assertFalse(result["compliance_ok"])
            self.assertIsNone(result["written"])
            self.assertIsNotNone(result["draft_kept"])
            self.assertTrue(Path(result["draft_kept"]).exists())
            self.assertFalse((Path(td) / "import_vegamovies.py").exists())

    def test_scaffold_writes_importer_when_draft_is_clean(self):
        bp = {"site_name": "vegamovies", "base_url": "https://vegamovies.to"}
        good_draft = (
            "```python\nimport urllib.request, sqlite3\n"
            "from pathlib import Path\n"
            "DB = Path('/home/ubuntu/radd-stream-data/vegamovies.db')\n"
            "print(DB)\n```"
        )
        with TemporaryDirectory() as td:
            result = site_scout.SiteScout("https://vegamovies.to", opener=FakeOpener([])).scaffold(
                bp, draft_fn=lambda prompt: good_draft, out_dir=Path(td)
            )
            self.assertTrue(result["accepted"], result["reasons"])
            self.assertTrue(Path(result["written"]).exists())
            self.assertEqual(Path(result["written"]).name, "import_vegamovies.py")


class BridgeTracerTests(unittest.TestCase):
    def test_hop_chain_is_recorded_with_patterns(self):
        opener = FakeTracerOpener([
            ("hubcloud.ist/drive/ABC", 302, "", {"Location": "https://gamerxyt.com/hubcloud.php?id=ABC"}),
            ("gamerxyt.com", 200, '<a href="https://pub-x.r2.dev/file.mkv?token=z">R2</a>', {}),
        ])
        result = bridge_tracer.BridgeTracer(opener=opener, max_hops=2).trace("https://hubcloud.ist/drive/ABC")
        self.assertGreaterEqual(len(result["hop_chain"]), 2)
        self.assertTrue(result["read_only"])
        self.assertIn("hubcloud_drive", result["patterns_observed"])

    def test_challenge_stops_trace_honestly(self):
        opener = FakeTracerOpener([("walled", 200, CHALLENGE_HTML, {})])
        result = bridge_tracer.BridgeTracer(opener=opener, max_hops=2).trace("https://walled.example/p")
        self.assertTrue(result["blocked"])
        self.assertEqual(result["hop_chain"][-1]["note"], "blocked: challenge")

    def test_pixeldrain_direct_pattern_detected(self):
        opener = FakeTracerOpener([("pixeldrain", 200, "", {})])
        result = bridge_tracer.BridgeTracer(opener=opener).trace("https://pixeldrain.com/u/abc123")
        self.assertIn("pixeldrain_direct", result["patterns_observed"])

    def test_local_greenmotors_decode(self):
        import base64 as _b64
        import codecs as _codecs
        dest = "https://hblinks.lol/archives/119453"
        obj = json.dumps({"o": _b64.b64encode(dest.encode()).decode()})
        payload = _b64.b64encode(_b64.b64encode(_codecs.encode(_b64.b64encode(obj.encode()).decode(), "rot_13").encode()).decode().encode()).decode()
        self.assertEqual(bridge_tracer.decode_greenmotors_payload(payload), dest)


if __name__ == "__main__":
    unittest.main(verbosity=2)
