#!/usr/bin/env python3
"""
test_domain_resolver.py — Unit tests for the Session 106 domain tracker.

Covers domain_resolver.py (resolve_site chain, content verification,
registry v2) and the importer wiring (every importer reads the registry).

100% Python Standard Library. Zero external dependencies. Offline — the
network is a stub fetcher in every test; no live request is ever made.
The one live proof (the chain resolving all 19 real sites) runs from the
Oracle VM, not here; its results are in the Session 106 checkpoint.

Tests:
  1. verify_candidate: wp-json pass / IPTV-spam reject / no-quality-marker
     reject / empty / not-JSON / link-elsewhere; sitemap pass / thin-doorway
     reject / sitemapindex with 2 locs / no-same-host / sitemap on an
     unrelated host (live hdtvb->geekextreme catch); homepage pass /
     too-small / no-slug / parked markers / hijack redirect / CF challenge.
  2. resolve_site (stub fetcher + temp registry): cached hit, mirror
     fallback, GitHub hit, TLD probe incl. www variant (chain gap a),
     numeric probe, sister harvest, DDG hit, DDG slug-only filter +
     unrelated-host-never-verifies (live hdtvb->geekextreme catch),
     Telegram hit, all-fail -> "" with the old base kept (never a guessed
     domain), CF-only -> status unverifiable.
  3. Registry v2: load/save round-trip, get_active_base_url fallback,
     probe_site shift updates the registry, probe_all_sites only_stale
     skips a freshly verified site.
  4. Importer wiring: every import_*.py reads the registry
     (get_active_base_url), and three real clients resolve their base
     from the shipped registry.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import domain_resolver as dr

WP_GOOD = json.dumps([
    {"link": "https://new1.ssrmovies.page/post/one/",
     "title": {"rendered": "The Great Indian Kapil Show S05 1080p 720p WEB-DL"}},
    {"link": "https://new1.ssrmovies.page/post/two/",
     "title": {"rendered": "Pushpa 2 The Rule 2024 Hindi 720p HDRip"}},
])
WP_IPTV_SPAM = json.dumps([
    {"link": "https://ssrmovies.vip/post/one/",
     "title": {"rendered": "MagentaTV kostenlos testen - 8K IPTV USA"}},
    {"link": "https://ssrmovies.vip/post/two/",
     "title": {"rendered": "Best IPTV Subscription 2026 - 8K IPTV USA"}},
])
WP_NO_MARKER = json.dumps([
    {"link": "https://new1.ssrmovies.page/post/one/",
     "title": {"rendered": "A Quiet Drama Without Any Quality Tag"}},
])
SITEMAP_GOOD = "<urlset>" + "".join(
    f"<url><loc>https://vegamovies.lease/post-{i}/</loc></url>" for i in range(12)
) + "</urlset>"
SITEMAP_THIN = "<urlset><url><loc>https://vegamovies.xyz/lander</loc></url></urlset>"
SITEMAP_INDEX = ("<sitemapindex>"
                 "<sitemap><loc>https://vegamovies.lease/s1.xml</loc></sitemap>"
                 "<sitemap><loc>https://vegamovies.lease/s2.xml</loc></sitemap>"
                 "</sitemapindex>")
SITEMAP_FOREIGN = "<urlset>" + "".join(
    f"<url><loc>https://other-site.test/post-{i}/</loc></url>" for i in range(12)
) + "</urlset>"
HOMEPAGE_GOOD = (
    "<html><head><title>Hindilinks4u - Watch Hindi Movies Online</title></head><body>"
    + "<p>" + ("Hindi movie news, reviews and download updates. " * 80) + "</p>"
    + "".join(f'<a href="https://www.hindilinks4u.zip/movie-{i}/">Movie {i}</a>'
              for i in range(5))
    + "</body></html>"
)
HOMEPAGE_PARKED = "<html><head><title>hindilinks4u.zip</title></head><body>" + ("x" * 3000) + \
    "<p>This domain is for sale — buy this domain now on Sedo.</p></body></html>"


def wp_entry(site="ssrmovies", slugs=None, base="https://new1.ssrmovies.page"):
    return {"site_name": site, "slug_variants": slugs or [site],
            "api_type": "wp_rest_api", "active_base_url": base}


def sitemap_entry(site="vegamovies"):
    return {"site_name": site, "slug_variants": [site],
            "api_type": "xml_sitemap",
            "active_base_url": f"https://{site}.lease"}


def home_entry(site="hindilinks4u"):
    return {"site_name": site, "slug_variants": [site],
            "api_type": "homepage",
            "active_base_url": f"https://www.{site}.zip"}


class StubFetch:
    """A stub fetcher: routes are exact-URL -> (status, final_url, text, error).

    Unrouted URLs fail closed (status 0, 'unrouted') so a test that forgets
    a route fails loudly instead of silently passing on an empty body.
    """

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, url, timeout=8, max_bytes=200_000):
        self.calls.append(url)
        for prefix, value in self.routes.items():
            if url == prefix or url.startswith(prefix + "?"):
                return value
        return (0, url, "", "unrouted-stub-url")


class VerifyCandidateTests(unittest.TestCase):
    def test_wp_good_passes(self):
        ok, reason, by = dr.verify_candidate(
            wp_entry(), "https://new1.ssrmovies.page", 200,
            "https://new1.ssrmovies.page/wp-json/wp/v2/posts?per_page=3", WP_GOOD)
        self.assertTrue(ok, reason)
        self.assertEqual(by, "wp-json")

    def test_wp_iptv_spam_rejected(self):
        # Chain gap (b): ssrmovies.vip passed the old host-only check with
        # all-IPTV posts. The content-kind check must reject it.
        ok, reason, _ = dr.verify_candidate(
            wp_entry(), "https://ssrmovies.vip", 200,
            "https://ssrmovies.vip/wp-json/wp/v2/posts?per_page=3", WP_IPTV_SPAM)
        self.assertFalse(ok)
        self.assertEqual(reason, "wp-json-iptv-spam")

    def test_wp_no_quality_marker_rejected(self):
        ok, reason, _ = dr.verify_candidate(
            wp_entry(), "https://new1.ssrmovies.page", 200,
            "https://new1.ssrmovies.page/wp-json/wp/v2/posts?per_page=3", WP_NO_MARKER)
        self.assertFalse(ok)
        self.assertEqual(reason, "wp-json-no-quality-marker")

    def test_wp_empty_and_not_json_rejected(self):
        for body, want in (("[]", "wp-json-empty"),
                           ("not json at all", "wp-json-not-json")):
            ok, reason, _ = dr.verify_candidate(
                wp_entry(), "https://new1.ssrmovies.page", 200,
                "https://new1.ssrmovies.page/wp-json/wp/v2/posts?per_page=3", body)
            self.assertFalse(ok)
            self.assertEqual(reason, want)

    def test_wp_link_elsewhere_rejected(self):
        body = json.dumps([{"link": "https://other-host.test/post/",
                            "title": {"rendered": "Movie 2024 720p WEB-DL"}}])
        ok, reason, _ = dr.verify_candidate(
            wp_entry(), "https://new1.ssrmovies.page", 200,
            "https://new1.ssrmovies.page/wp-json/wp/v2/posts?per_page=3", body)
        self.assertFalse(ok)
        self.assertTrue(reason.startswith("wp-json-link-elsewhere"))

    def test_sitemap_good_passes(self):
        ok, reason, by = dr.verify_candidate(
            sitemap_entry(), "https://vegamovies.lease", 200,
            "https://vegamovies.lease/sitemap.xml", SITEMAP_GOOD)
        self.assertTrue(ok, reason)
        self.assertEqual(by, "sitemap")

    def test_sitemap_thin_doorway_rejected(self):
        # vegamovies.xyz served a valid sitemap with exactly 1 loc (…/lander).
        ok, reason, _ = dr.verify_candidate(
            sitemap_entry(), "https://vegamovies.xyz", 200,
            "https://vegamovies.xyz/sitemap.xml", SITEMAP_THIN)
        self.assertFalse(ok)
        self.assertEqual(reason, "sitemap-too-thin:1-locs")

    def test_sitemap_index_with_two_locs_passes(self):
        ok, reason, _ = dr.verify_candidate(
            sitemap_entry(), "https://vegamovies.lease", 200,
            "https://vegamovies.lease/sitemap.xml", SITEMAP_INDEX)
        self.assertTrue(ok, reason)

    def test_sitemap_no_same_host_rejected(self):
        ok, reason, _ = dr.verify_candidate(
            sitemap_entry(), "https://vegamovies.lease", 200,
            "https://vegamovies.lease/sitemap.xml", SITEMAP_FOREIGN)
        self.assertFalse(ok)
        self.assertEqual(reason, "sitemap-no-same-host-loc")

    def test_homepage_good_passes(self):
        ok, reason, by = dr.verify_candidate(
            home_entry(), "https://www.hindilinks4u.zip", 200,
            "https://www.hindilinks4u.zip/", HOMEPAGE_GOOD)
        self.assertTrue(ok, reason)
        self.assertEqual(by, "homepage")

    def test_homepage_parked_rejected(self):
        ok, reason, _ = dr.verify_candidate(
            home_entry(), "https://www.hindilinks4u.zip", 200,
            "https://www.hindilinks4u.zip/", HOMEPAGE_PARKED)
        self.assertFalse(ok)
        self.assertTrue(reason.startswith("parked-marker:"))

    def test_homepage_too_small_rejected(self):
        ok, reason, _ = dr.verify_candidate(
            home_entry(), "https://www.hindilinks4u.zip", 200,
            "https://www.hindilinks4u.zip/", "<html><title>hi</title></html>")
        self.assertFalse(ok)
        self.assertTrue(reason.startswith("homepage-too-small:"))

    def test_hijack_redirect_rejected(self):
        # desicinemas.tv -> koi5000sultan.com: the final host lacks the slug.
        ok, reason, _ = dr.verify_candidate(
            {"site_name": "desicinemas", "slug_variants": ["desicinemas"],
             "api_type": "xml_sitemap"},
            "https://desicinemas.tv", 200,
            "https://koi5000sultan.com/", SITEMAP_GOOD)
        self.assertFalse(ok)
        self.assertEqual(reason, "host-no-site-slug:koi5000sultan.com")

    def test_sitemap_on_unrelated_host_rejected(self):
        # Live catch 2026-11-08: hdtvb -> www.geekextreme.com, a tech blog
        # whose sitemapindex (19 sub-sitemaps) passed the sitemap branch.
        # The final host never carried the site slug, so it must fail here
        # no matter how structurally perfect the sitemap is.
        index = ("<sitemapindex>" + "".join(
            f"<sitemap><loc>https://www.geekextreme.com/s{i}.xml</loc></sitemap>"
            for i in range(19)) + "</sitemapindex>")
        ok, reason, _ = dr.verify_candidate(
            {"site_name": "hdtvb", "slug_variants": ["hdtvb", "hdutv"],
             "api_type": "xml_sitemap"},
            "https://www.geekextreme.com", 200,
            "https://www.geekextreme.com/sitemap.xml", index)
        self.assertFalse(ok)
        self.assertEqual(reason, "host-no-site-slug:www.geekextreme.com")

    def test_cloudflare_challenge_is_a_fail_with_its_own_reason(self):
        ok, reason, _ = dr.verify_candidate(
            wp_entry(), "https://new1.ssrmovies.page", 403,
            "https://new1.ssrmovies.page/wp-json/wp/v2/posts?per_page=3",
            "<html><title>Just a moment...</title></html>")
        self.assertFalse(ok)
        self.assertEqual(reason, "cloudflare-challenge http403")

    def test_no_response_is_a_fail(self):
        ok, reason, _ = dr.verify_candidate(wp_entry(), "https://new1.ssrmovies.page",
                                            0, "https://new1.ssrmovies.page", "")
        self.assertFalse(ok)
        self.assertEqual(reason, "no-response")


def temp_registry(sites):
    tmp = tempfile.TemporaryDirectory()
    path = Path(tmp.name) / "domain_registry.json"
    path.write_text(json.dumps({"version": "2.0", "sites": sites}), encoding="utf-8")
    return tmp, path


def site_entry(**over):
    entry = {"active_base_url": "https://new1.ssrmovies.page",
             "known_mirrors": ["https://new1.ssrmovies.page"],
             "slug_variants": ["ssrmovies"], "tld_history": ["page", "surf"],
             "api_type": "wp_rest_api", "status": "active"}
    entry.update(over)
    return entry


class ResolveSiteTests(unittest.TestCase):
    def test_cached_hit_returns_base_and_refreshes_registry(self):
        tmp, path = temp_registry({"ssrmovies": site_entry()})
        stub = StubFetch({
            "https://new1.ssrmovies.page/wp-json/wp/v2/posts": (
                200, "https://new1.ssrmovies.page/wp-json/wp/v2/posts?per_page=3", WP_GOOD, None),
        })
        got = dr.resolve_site("ssrmovies", registry_path=path, fetcher=stub)
        self.assertEqual(got, "https://new1.ssrmovies.page")
        self.assertEqual(len(stub.calls), 1)  # one probe, no chain steps
        reg = dr.load_registry(path)
        self.assertEqual(reg["sites"]["ssrmovies"]["verified_by"], "wp-json")
        self.assertTrue(reg["sites"]["ssrmovies"]["last_verified"])
        tmp.cleanup()

    def test_mirror_fallback_records_rotation(self):
        tmp, path = temp_registry({"ssrmovies": site_entry(
            known_mirrors=["https://new1.ssrmovies.page", "https://ssrmovies.surf"])})
        stub = StubFetch({
            "https://new1.ssrmovies.page/wp-json/wp/v2/posts": (
                0, "https://new1.ssrmovies.page/wp-json/wp/v2/posts?per_page=3", "", "timeout"),
            "https://ssrmovies.surf/wp-json/wp/v2/posts": (
                200, "https://ssrmovies.surf/wp-json/wp/v2/posts?per_page=3", WP_GOOD.replace(
                    "new1.ssrmovies.page", "ssrmovies.surf"), None),
        })
        got = dr.resolve_site("ssrmovies", registry_path=path, fetcher=stub)
        self.assertEqual(got, "https://ssrmovies.surf")
        reg = dr.load_registry(path)
        hist = reg["sites"]["ssrmovies"]["rotation_history"]
        self.assertEqual(hist[0]["domain"], "https://new1.ssrmovies.page")
        self.assertEqual(hist[1]["domain"], "https://ssrmovies.surf")
        tmp.cleanup()

    def test_github_hit_when_cached_and_mirrors_fail(self):
        tmp, path = temp_registry({"hdhub4u": site_entry(
            active_base_url="https://new8.hdhub4u.cl",
            known_mirrors=["https://new8.hdhub4u.cl"],
            slug_variants=["hdhub4u"], tld_history=["cl"],
            api_type="xml_sitemap")})
        dr._GITHUB_CACHE["lists"] = {}
        dr._GITHUB_CACHE["fetched_at"] = 0.0
        stub = StubFetch({
            "https://raw.githubusercontent.com/SaurabhKaperwan/Utils/refs/heads/main/urls.json": (
                200, "https://raw.githubusercontent.com/x/urls.json",
                json.dumps({"hdhub4u": "https://new12.hdhub4u.cl"}), None),
            "https://raw.githubusercontent.com/phisher98/TVVVV/refs/heads/main/domains.json": (
                200, "https://raw.githubusercontent.com/x/domains.json",
                json.dumps({"hdhub4u": "https://new12.hdhub4u.cl"}), None),
            "https://new12.hdhub4u.cl/sitemap.xml": (
                200, "https://new12.hdhub4u.cl/sitemap.xml", SITEMAP_GOOD.replace(
                    "vegamovies.lease", "new12.hdhub4u.cl"), None),
        })
        # The sitemap fixture is vegamovies-shaped; rebuild it for hdhub4u.
        stub.routes["https://new12.hdhub4u.cl/sitemap.xml"] = (
            200, "https://new12.hdhub4u.cl/sitemap.xml",
            "<urlset>" + "".join(
                f"<url><loc>https://new12.hdhub4u.cl/post-{i}/</loc></url>"
                for i in range(12)) + "</urlset>", None)
        # The registry entry needs github_keys for the chain to consult the lists.
        reg = dr.load_registry(path)
        reg["sites"]["hdhub4u"]["github_keys"] = {"saurabh": "hdhub4u", "phisher": "hdhub4u"}
        dr.save_registry(reg, path)
        got = dr.resolve_site("hdhub4u", registry_path=path, fetcher=stub)
        self.assertEqual(got, "https://new12.hdhub4u.cl")
        tmp.cleanup()

    def test_tld_probe_tries_www_variant(self):
        # Chain gap (a): rareanimes.fans 301s to www.rareanimes.fans and the
        # bare probe never proves the site. The www variant must be tried.
        tmp, path = temp_registry({"rareanimes": site_entry(
            active_base_url="https://www.rareanimes.mov",
            known_mirrors=["https://www.rareanimes.mov"],
            slug_variants=["rareanimes"], tld_history=["fans", "mov"],
            api_type="wp_rest_api")})
        good_www = WP_GOOD.replace("new1.ssrmovies.page", "www.rareanimes.fans")
        stub = StubFetch({
            "https://www.rareanimes.fans/wp-json/wp/v2/posts": (
                200, "https://www.rareanimes.fans/wp-json/wp/v2/posts?per_page=3",
                good_www, None),
        })
        got = dr.resolve_site("rareanimes", registry_path=path, fetcher=stub)
        self.assertEqual(got, "https://www.rareanimes.fans")
        self.assertTrue(any("www.rareanimes.fans" in c for c in stub.calls))
        tmp.cleanup()

    def test_numeric_probe_finds_filmyzilla(self):
        tmp, path = temp_registry({"filmyzilla": site_entry(
            active_base_url="https://thefilmyzilla.in",
            known_mirrors=["https://thefilmyzilla.in"],
            slug_variants=["filmyzilla", "thefilmyzilla"], tld_history=["in", "com"],
            api_type="xml_sitemap",
            numeric_pattern={"stem": "filmyzilla", "tld": "com", "range": [70, 95]})})
        sitemap80 = ("<urlset>" + "".join(
            f"<url><loc>https://www.filmyzilla80.com/post-{i}/</loc></url>"
            for i in range(12)) + "</urlset>")
        stub = StubFetch({
            "https://www.filmyzilla80.com/sitemap.xml": (
                200, "https://www.filmyzilla80.com/sitemap.xml", sitemap80, None),
        })
        got = dr.resolve_site("filmyzilla", registry_path=path, fetcher=stub)
        self.assertEqual(got, "https://www.filmyzilla80.com")
        tmp.cleanup()

    def test_sister_harvest_finds_a_new_domain(self):
        tmp, path = temp_registry({"ssrmovies": site_entry()})
        homepage = ('<html><head><title>SSRMovies</title></head><body>'
                    '<a href="https://ssrmovies.foo/new-domain/">New domain</a>'
                    '</body></html>')
        stub = StubFetch({
            "https://new1.ssrmovies.page": (
                200, "https://new1.ssrmovies.page/", homepage, None),
            "https://ssrmovies.foo/wp-json/wp/v2/posts": (
                200, "https://ssrmovies.foo/wp-json/wp/v2/posts?per_page=3",
                WP_GOOD.replace("new1.ssrmovies.page", "ssrmovies.foo"), None),
        })
        got = dr.resolve_site("ssrmovies", registry_path=path, fetcher=stub)
        self.assertEqual(got, "https://ssrmovies.foo")
        tmp.cleanup()

    def test_ddg_hit_when_everything_else_fails(self):
        tmp, path = temp_registry({"ssrmovies": site_entry(
            tld_history=["page"], known_mirrors=["https://new1.ssrmovies.page"])})
        ddg_page = ('<html><body>'
                    '<a class="result__a" href="//duckduckgo.com/l/?uddg='
                    'https%3A%2F%2Fnew9.ssrmovies.page%2F">ssrmovies new domain</a>'
                    '</body></html>')
        stub = StubFetch({
            "https://html.duckduckgo.com/html/?q=ssrmovies+new+domain+official+site": (
                200, "https://html.duckduckgo.com/html/?q=ssrmovies+new+domain+official+site",
                ddg_page, None),
            "https://new9.ssrmovies.page/wp-json/wp/v2/posts": (
                200, "https://new9.ssrmovies.page/wp-json/wp/v2/posts?per_page=3",
                WP_GOOD.replace("new1.ssrmovies.page", "new9.ssrmovies.page"), None),
        })
        got = dr.resolve_site("ssrmovies", registry_path=path, fetcher=stub)
        self.assertEqual(got, "https://new9.ssrmovies.page")
        tmp.cleanup()

    def test_ddg_returns_slug_hosts_only(self):
        # Live catch 2026-11-08: DDG returned www.geekextreme.com for the
        # hdtvb query; the non-slug tail of the ranking let it verify.
        ddg_page = ('<html><body>'
                    '<a class="result__a" href="//duckduckgo.com/l/?uddg='
                    'https%3A%2F%2Fwww.geekextreme.com%2F">geek extreme</a>'
                    '<a class="result__a" href="//duckduckgo.com/l/?uddg='
                    'https%3A%2F%2Fnew3.hdtvb.net%2F">hdtvb new domain</a>'
                    '</body></html>')
        stub = StubFetch({
            "https://html.duckduckgo.com/html/?q=hdtvb+new+domain+official+site": (
                200, "https://html.duckduckgo.com/html/?q=hdtvb+new+domain+official+site",
                ddg_page, None),
        })
        hosts, _note = dr.ddg_search("hdtvb", fetcher=stub)
        self.assertIn("new3.hdtvb.net", hosts)
        self.assertNotIn("www.geekextreme.com", hosts)

    def test_ddg_unrelated_host_never_verifies(self):
        # End-to-end version of the live catch: cached base and mirrors
        # are dead, the TLD sweep finds nothing, DDG returns an unrelated
        # host whose sitemap is structurally perfect — the chain must still
        # give up with the old base kept and status down.
        tmp, path = temp_registry({"hdtvb": site_entry(
            active_base_url="https://hdutv.com",
            known_mirrors=["https://hdutv.com", "https://hdtvb.net"],
            slug_variants=["hdtvb", "hdutv"], tld_history=["net", "com"],
            api_type="xml_sitemap", status="retired")})
        index = ("<sitemapindex>" + "".join(
            f"<sitemap><loc>https://www.geekextreme.com/s{i}.xml</loc></sitemap>"
            for i in range(19)) + "</sitemapindex>")
        ddg_page = ('<html><body>'
                    '<a class="result__a" href="//duckduckgo.com/l/?uddg='
                    'https%3A%2F%2Fwww.geekextreme.com%2F">geek extreme</a>'
                    '</body></html>')
        stub = StubFetch({
            "https://html.duckduckgo.com/html/?q=hdtvb+new+domain+official+site": (
                200, "https://html.duckduckgo.com/html/?q=hdtvb+new+domain+official+site",
                ddg_page, None),
            "https://www.geekextreme.com/sitemap.xml": (
                200, "https://www.geekextreme.com/sitemap.xml", index, None),
        })
        got = dr.resolve_site("hdtvb", registry_path=path, fetcher=stub)
        self.assertEqual(got, "")
        reg = dr.load_registry(path)
        entry = reg["sites"]["hdtvb"]
        self.assertEqual(entry["active_base_url"], "https://hdutv.com")
        self.assertEqual(entry["status"], "down")
        tmp.cleanup()

    def test_telegram_hit(self):
        # The Telegram step must be proven on its own: the announced host
        # (new9.vegamovies.lease) is NOT in the TLD candidate list, so the
        # chain can only find it through the channel post.
        tmp, path = temp_registry({"vegamovies": site_entry(
            active_base_url="https://vegamovies.gallery",
            known_mirrors=["https://vegamovies.gallery"],
            slug_variants=["vegamovies"], tld_history=["lease", "gallery"],
            api_type="xml_sitemap", telegram_channel="vega_officials")})
        tg_page = ('<html><body><div class="tgme_widget_message_text">'
                   'New Domain: https://new9.vegamovies.lease - bookmark it!</div></body></html>')
        sitemap_new9 = ("<urlset>" + "".join(
            f"<url><loc>https://new9.vegamovies.lease/post-{i}/</loc></url>"
            for i in range(12)) + "</urlset>")
        stub = StubFetch({
            "https://t.me/s/vega_officials": (
                200, "https://t.me/s/vega_officials", tg_page, None),
            "https://new9.vegamovies.lease/sitemap.xml": (
                200, "https://new9.vegamovies.lease/sitemap.xml", sitemap_new9, None),
        })
        got = dr.resolve_site("vegamovies", registry_path=path, fetcher=stub)
        self.assertEqual(got, "https://new9.vegamovies.lease")
        tmp.cleanup()

    def test_all_fail_keeps_old_base_and_marks_down(self):
        # The hard rule: never write a guessed domain.
        tmp, path = temp_registry({"ssrmovies": site_entry()})
        stub = StubFetch({})
        got = dr.resolve_site("ssrmovies", registry_path=path, fetcher=stub)
        self.assertEqual(got, "")
        reg = dr.load_registry(path)
        entry = reg["sites"]["ssrmovies"]
        self.assertEqual(entry["active_base_url"], "https://new1.ssrmovies.page")
        self.assertEqual(entry["status"], "down")
        self.assertTrue(entry["last_checked"])
        tmp.cleanup()

    def test_cf_only_marks_unverifiable_not_down(self):
        tmp, path = temp_registry({"ssrmovies": site_entry()})
        cf_body = "<html><title>Just a moment...</title></html>"
        stub = StubFetch({
            "https://new1.ssrmovies.page/wp-json/wp/v2/posts": (
                403, "https://new1.ssrmovies.page/wp-json/wp/v2/posts?per_page=3",
                cf_body, None),
        })
        # The TLD sweep also hits the stub (unrouted -> status 0), so the
        # run is not CF-only; force it by routing every TLD candidate to CF.
        for cand in dr._tld_candidates(site_entry()):
            stub.routes[cand + "/wp-json/wp/v2/posts"] = (
                403, cand + "/wp-json/wp/v2/posts?per_page=3", cf_body, None)
        got = dr.resolve_site("ssrmovies", registry_path=path, fetcher=stub)
        self.assertEqual(got, "")
        reg = dr.load_registry(path)
        self.assertEqual(reg["sites"]["ssrmovies"]["status"], "unverifiable")
        self.assertEqual(reg["sites"]["ssrmovies"]["active_base_url"],
                         "https://new1.ssrmovies.page")
        tmp.cleanup()

    def test_unknown_site_returns_empty(self):
        tmp, path = temp_registry({})
        self.assertEqual(dr.resolve_site("nosuchsite", registry_path=path,
                                         fetcher=StubFetch({})), "")
        tmp.cleanup()


class ResolveIfDeadTests(unittest.TestCase):
    def test_healthy_site_returns_empty(self):
        # A 0-post sync on a healthy site means "nothing new", not "dead":
        # no chain run, no retry.
        tmp, path = temp_registry({"ssrmovies": site_entry()})
        stub = StubFetch({
            "https://new1.ssrmovies.page/wp-json/wp/v2/posts": (
                200, "https://new1.ssrmovies.page/wp-json/wp/v2/posts?per_page=3", WP_GOOD, None),
        })
        self.assertEqual(dr.resolve_if_dead("ssrmovies", registry_path=path,
                                            fetcher=stub), "")
        self.assertEqual(len(stub.calls), 1)
        tmp.cleanup()

    def test_dead_site_returns_chain_result(self):
        tmp, path = temp_registry({"ssrmovies": site_entry(
            known_mirrors=["https://new1.ssrmovies.page", "https://ssrmovies.surf"])})
        stub = StubFetch({
            "https://ssrmovies.surf/wp-json/wp/v2/posts": (
                200, "https://ssrmovies.surf/wp-json/wp/v2/posts?per_page=3",
                WP_GOOD.replace("new1.ssrmovies.page", "ssrmovies.surf"), None),
        })
        got = dr.resolve_if_dead("ssrmovies", registry_path=path, fetcher=stub)
        self.assertEqual(got, "https://ssrmovies.surf")
        tmp.cleanup()


class RegistryTests(unittest.TestCase):
    def test_get_active_base_url_fallback(self):
        tmp, path = temp_registry({"ssrmovies": site_entry()})
        self.assertEqual(dr.get_active_base_url("ssrmovies", "https://fallback.test",
                                                registry_path=path),
                         "https://new1.ssrmovies.page")
        self.assertEqual(dr.get_active_base_url("nosuchsite", "https://fallback.test",
                                                registry_path=path),
                         "https://fallback.test")
        self.assertEqual(dr.get_active_base_url("nosuchsite", registry_path=path), "")
        tmp.cleanup()

    def test_registry_v2_round_trip(self):
        tmp, path = temp_registry({"ssrmovies": site_entry()})
        reg = dr.load_registry(path)
        reg["sites"]["ssrmovies"]["last_verified"] = "2026-11-08T02:00:00Z"
        dr.save_registry(reg, path)
        again = dr.load_registry(path)
        self.assertEqual(again["version"], "2.0")
        self.assertEqual(again["sites"]["ssrmovies"]["last_verified"],
                         "2026-11-08T02:00:00Z")
        self.assertTrue(again["updated_at"])
        tmp.cleanup()

    def test_shipped_registry_is_v2_with_all_22_sites(self):
        reg = dr.load_registry()
        self.assertEqual(reg.get("version"), "2.0")
        self.assertEqual(len(reg["sites"]), 22)
        for name, entry in reg["sites"].items():
            self.assertTrue(entry.get("slug_variants"), name)
            self.assertTrue(entry.get("tld_history"), name)
            self.assertTrue(entry.get("api_type"), name)
            self.assertTrue(entry.get("active_base_url"), name)
        self.assertEqual(reg["sites"]["hdtvb"]["status"], "retired")
        self.assertEqual(reg["sites"]["vegamovies"]["telegram_channel"], "vega_officials")
        self.assertEqual(reg["sites"]["vegamovies"]["bookmark_domain"], "https://vglist.nl")
        self.assertEqual(reg["sites"]["hdhub4u"]["numeric_pattern"]["host"], "hdhub4u.cl")

    def test_probe_site_shift_updates_registry(self):
        tmp, path = temp_registry({"ssrmovies": site_entry(
            active_base_url="https://ssrmovies.surf",
            known_mirrors=["https://ssrmovies.surf", "https://new1.ssrmovies.page"])})
        stub = StubFetch({
            "https://new1.ssrmovies.page/wp-json/wp/v2/posts": (
                200, "https://new1.ssrmovies.page/wp-json/wp/v2/posts?per_page=3",
                WP_GOOD, None),
        })
        res = dr.probe_site("ssrmovies", registry_path=path, fetcher=stub)
        self.assertEqual(res["status"], "active")
        self.assertTrue(res["domain_shifted"])
        self.assertEqual(res["final_base_url"], "https://new1.ssrmovies.page")
        reg = dr.load_registry(path)
        self.assertEqual(reg["sites"]["ssrmovies"]["active_base_url"],
                         "https://new1.ssrmovies.page")
        tmp.cleanup()

    def test_probe_all_sites_only_stale_skips_fresh(self):
        tmp, path = temp_registry({"ssrmovies": site_entry()})
        reg = dr.load_registry(path)
        reg["sites"]["ssrmovies"]["last_verified"] = dr._now_iso()
        dr.save_registry(reg, path)
        results = dr.probe_all_sites(only_stale=True, registry_path=path,
                                     fetcher=StubFetch({}))
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].get("skipped"))
        tmp.cleanup()

    def test_tld_candidates_history_first_and_bounded(self):
        cands = dr._tld_candidates(site_entry(tld_history=["page", "surf"]))
        self.assertEqual(cands[0], "https://ssrmovies.page")
        self.assertEqual(cands[1], "https://www.ssrmovies.page")  # www variant, gap (a)
        self.assertLessEqual(len(cands), dr.MAX_TLD_PROBES)


class ImporterWiringTests(unittest.TestCase):
    def test_every_importer_reads_the_registry(self):
        # Source scan, in the PhoneCredentialGuardTest pattern: the wiring
        # guarantee is about the import path, and the only thing that proves
        # it without a crawl is reading that path.
        importers = sorted(BASE_DIR.glob("import_*.py"))
        self.assertEqual(len(importers), 22)
        for path in importers:
            src = path.read_text(encoding="utf-8")
            self.assertIn("from domain_resolver import", src, path.name)
            self.assertIn("get_active_base_url(SITE_NAME", src, path.name)

    def test_real_clients_resolve_from_the_shipped_registry(self):
        import import_10xflix
        import import_ssrmovies
        import import_vegamovies
        reg = dr.load_registry()
        self.assertEqual(import_10xflix.TenXFlixClient().base_url,
                         reg["sites"]["10xflix"]["active_base_url"])
        self.assertEqual(import_ssrmovies.SSRMoviesClient().base_url,
                         reg["sites"]["ssrmovies"]["active_base_url"])
        self.assertEqual(import_vegamovies.VegamoviesClient().base_url,
                         reg["sites"]["vegamovies"]["active_base_url"])


if __name__ == "__main__":
    unittest.main()
