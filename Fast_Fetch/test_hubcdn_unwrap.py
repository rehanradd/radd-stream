#!/usr/bin/env python3
"""Offline tests for the HubCDN gateway unwrap — the ``hubcdn.io/cloud/<id>``
bridge used by hdhub4u and hdtvb (crown order #54, 2026-11-05).

Stdlib only, zero network: every fetch goes through the ``_fetch`` / ``_hop``
seams that ``fast_fetch.unwrap_hubcdn`` already exposes, so each test names the
property it proves and none of them can slow a CI box or knock on a third party.

The point of the file is the trust gate: the gateway is untrusted input, and
every Location it answers with is judged by ``host_classifier`` — never by the
button's label and never by a substring. Tests named ``refuses``/``buy`` are the
counterfactual anchors: sabotage ``hubcdn_asset_role`` to accept anything and
they go red.

    python3 -S Fast_Fetch/test_hubcdn_unwrap.py
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.resolve()))

import fast_fetch  # noqa: E402
import host_classifier as hc  # noqa: E402

R2_ASSET = "https://pub-abc123.r2.dev/movie.mkv"
GOOGLE_ASSET = "https://video-downloads.googleusercontent.com/dl/movie"


def gateway_page(buttons) -> str:
    """Build a gateway page from ``[(attrs, label), ...]`` button specs."""
    anchors = "\n".join(f'<a {attrs}>{label}</a>' for attrs, label in buttons)
    return f"<html><head><title>Movie 1080p - HubCDN</title></head><body>{anchors}</body></html>"


def trigger(href: str, label: str = "Download") -> tuple[str, str]:
    return (f'class="btn dl-trigger" href="{href}"', label)


class HopRecorder:
    """The ``_hop`` seam: answers fixed statuses and keeps every header it saw.

    ``unwrap_hubcdn`` stamps a fresh ``dl_token`` onto each button href, so the
    lookup strips it before matching — the token itself is asserted separately.
    """

    def __init__(self, hops: dict[str, tuple[int, str]]):
        self.hops = hops
        self.urls: list[str] = []
        self.headers: list[dict] = []

    def __call__(self, url: str, headers: dict) -> tuple[int, str]:
        self.urls.append(url)
        self.headers.append(dict(headers))
        stripped = re.sub(r"[&?]dl_token=[^&]*", "", url)
        return self.hops.get(stripped, (404, ""))


HAPPY_BUTTONS = [
    trigger("/l.php?id=9&amp;t=a", "480p [500MB]"),
    trigger("https://hubcdn.io/l.php?id=10", "1080p [4.2GB]"),
]


def happy_hops() -> dict:
    return {
        "https://hubcdn.io/l.php?id=9&t=a": (302, R2_ASSET),
        "https://hubcdn.io/l.php?id=10": (302, GOOGLE_ASSET),
    }


class BridgeRecognitionTests(unittest.TestCase):
    """is_bridge_url must agree with host_classifier._HOST_TABLE on hubcdn."""

    def test_hubcdn_cloud_page_is_a_bridge(self):
        self.assertTrue(fast_fetch.is_bridge_url("https://hubcdn.io/cloud/abc123"))

    def test_hubcdn_cloud_page_with_query_is_a_bridge(self):
        self.assertTrue(fast_fetch.is_bridge_url("https://hubcdn.io/cloud/abc?x=1"))

    def test_hubcdn_subdomain_is_a_bridge(self):
        self.assertTrue(fast_fetch.is_bridge_url("https://www.hubcdn.io/cloud/abc"))

    def test_lookalike_host_containing_the_hubcdn_name_is_not_a_bridge(self):
        self.assertFalse(fast_fetch.is_bridge_url("https://hubcdnio.attacker.tld/cloud/abc"))

    def test_hubcdn_path_on_another_host_is_not_a_bridge(self):
        self.assertFalse(fast_fetch.is_bridge_url("https://example.com/hubcdn.io/cloud/x"))

    def test_bridge_verdict_agrees_with_the_classifier_category(self):
        verdict = hc.classify("https://hubcdn.io/cloud/abc")
        self.assertEqual(verdict.category, hc.CATEGORY_BRIDGE)
        self.assertTrue(fast_fetch.is_bridge_url("https://hubcdn.io/cloud/abc"))

    def test_a_bridge_is_never_a_direct_media_url(self):
        self.assertFalse(fast_fetch.is_direct_media_url("https://hubcdn.io/cloud/abc"))


class PagePredicateTests(unittest.TestCase):

    def test_cloud_path_is_the_only_unwrappable_page_shape(self):
        self.assertTrue(hc.is_hubcdn_cloud_page("https://hubcdn.io/cloud/abc"))
        self.assertFalse(hc.is_hubcdn_cloud_page("https://hubcdn.io/file/abc"))
        self.assertFalse(hc.is_hubcdn_cloud_page("https://hubcdn.io/"))


class TrustGateTests(unittest.TestCase):
    """Every Location the gateway hands back is judged by the authority table."""

    def test_role_accepts_public_r2_bucket_as_stream(self):
        self.assertEqual(hc.hubcdn_asset_role("https://pub-z9.r2.dev/a.mkv"), "stream")

    def test_role_accepts_google_front_as_download(self):
        self.assertEqual(
            hc.hubcdn_asset_role("https://video-downloads.googleusercontent.com/a"),
            "download")

    def test_role_refuses_raw_r2_api_host_without_the_pub_prefix(self):
        self.assertIsNone(hc.hubcdn_asset_role("https://abc.r2.dev/a.mkv"))

    def test_role_refuses_r2_lookalike_suffixes(self):
        for hostile in ("https://r2.dev.attacker.tld/x.mkv",
                        "https://pub-abc.r2.dev.evil.cn/y.mkv"):
            with self.subTest(hostile):
                self.assertIsNone(hc.hubcdn_asset_role(hostile))

    def test_role_refuses_google_front_lookalike_subdomain(self):
        self.assertIsNone(hc.hubcdn_asset_role(
            "https://video-downloads.googleusercontent.com.evil.cn/z"))

    def test_service_stamp_names_the_serving_cdn_not_the_gateway(self):
        self.assertEqual(hc.hubcdn_asset_service(R2_ASSET), "fsl_r2")
        self.assertEqual(hc.hubcdn_asset_service(GOOGLE_ASSET), "google_cdn")
        self.assertIsNone(hc.hubcdn_asset_service("https://r2.dev.attacker.tld/x.mkv"))


class ButtonParsingTests(unittest.TestCase):

    def test_only_dl_trigger_anchors_become_buttons(self):
        page = gateway_page([
            trigger("/l.php?id=1", "Real"),
            ('href="https://hubcdn.io/l.php?id=2"', "Not a trigger"),
        ])
        buttons = hc.hubcdn_page_buttons(page)
        self.assertEqual(len(buttons), 1)

    def test_ampersand_escaped_href_is_unescaped(self):
        page = gateway_page([trigger("/l.php?id=9&amp;t=a")])
        href, _label = hc.hubcdn_page_buttons(page)[0]
        self.assertEqual(href, "/l.php?id=9&t=a")

    def test_href_survive_reordered_anchor_attributes(self):
        page = '<a href="/l.php?id=3" class="dl-trigger">x</a>'
        self.assertEqual(len(hc.hubcdn_page_buttons(page)), 1)


class TokenTests(unittest.TestCase):

    def test_token_added_to_a_bare_href(self):
        out = hc.hubcdn_with_token("https://hubcdn.io/l.php", "t1")
        self.assertEqual(out, "https://hubcdn.io/l.php?dl_token=t1")

    def test_token_appended_without_disturbing_the_existing_query(self):
        out = hc.hubcdn_with_token("https://hubcdn.io/l.php?id=9", "t1")
        self.assertTrue(out.endswith("id=9&dl_token=t1"), out)
        self.assertIn("?", out)
        self.assertEqual(out.count("?"), 1)

    def test_root_relative_href_resolves_against_the_gateway_host(self):
        self.assertEqual(hc.hubcdn_resolve_href("/l.php?id=9"),
                         "https://hubcdn.io/l.php?id=9")


class UnwrapTests(unittest.TestCase):
    """unwrap_hubcdn end to end, with both network edges injected."""

    def unwrap(self, hops, buttons=None, cookies="session=xyz", url=None):
        page = gateway_page(HAPPY_BUTTONS if buttons is None else buttons)
        recorder = HopRecorder(hops)
        res = fast_fetch.unwrap_hubcdn(
            url or "https://hubcdn.io/cloud/abc123",
            _fetch=lambda u: (page, cookies), _hop=recorder)
        return res, recorder

    def test_happy_page_yields_both_assets(self):
        res, _rec = self.unwrap(happy_hops())
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["r2_url"], R2_ASSET)
        self.assertEqual(res["google_url"], GOOGLE_ASSET)

    def test_title_drops_the_gateway_suffix(self):
        res, _rec = self.unwrap(happy_hops())
        self.assertEqual(res["title"], "Movie 1080p")

    def test_referer_and_token_reach_every_hop(self):
        res, rec = self.unwrap(happy_hops())
        self.assertTrue(res["ok"], res)
        self.assertEqual(len(rec.urls), 2)
        for url, headers in zip(rec.urls, rec.headers):
            self.assertEqual(headers.get("Referer"), "https://hubcdn.io/cloud/abc123")
            self.assertIn("dl_token=", url)

    def test_size_is_taken_from_the_button_label(self):
        res, _rec = self.unwrap(happy_hops())
        self.assertEqual(res["size_str"], "500MB")

    def test_slotting_is_by_role_not_button_order(self):
        buttons = [  # google button FIRST this time
            trigger("https://hubcdn.io/l.php?id=10", "1080p [4.2GB]"),
            trigger("/l.php?id=9&amp;t=a", "480p [500MB]"),
        ]
        res, _rec = self.unwrap(happy_hops(), buttons=buttons)
        self.assertEqual(res["r2_url"], R2_ASSET)
        self.assertEqual(res["google_url"], GOOGLE_ASSET)

    def test_dispatch_prefers_the_r2_stream_when_both_exist(self):
        # Mirrors the resolve_live_source refresh (`fresh_url = res.get("r2_url")
        # or res.get("google_url")`): the bucket copy is the streamable one.
        res, _rec = self.unwrap(happy_hops())
        fresh_url = res.get("r2_url") or res.get("google_url")
        self.assertEqual(fresh_url, R2_ASSET)

    def test_download_survives_alone_when_the_bucket_hop_fails(self):
        lone = {"https://hubcdn.io/l.php?id=10": (302, GOOGLE_ASSET)}
        res, _rec = self.unwrap(lone)
        self.assertTrue(res["ok"], res)
        self.assertIsNone(res["r2_url"])
        self.assertEqual(res["google_url"], GOOGLE_ASSET)

    def test_hostile_locations_buy_no_asset(self):
        hostile_buttons = [
            trigger("/l.php?id=9&amp;t=a", "bucket trick"),
            trigger("/l.php?id=10&amp;t=b", "suffix trick"),
        ]
        hops = {
            "https://hubcdn.io/l.php?id=9&t=a": (302, "https://r2.dev.attacker.tld/x.mkv"),
            "https://hubcdn.io/l.php?id=10&t=b": (302, "https://pub-abc.r2.dev.evil.cn/y.mkv"),
        }
        res, _rec = self.unwrap(hops, buttons=hostile_buttons)
        self.assertFalse(res["ok"], res)
        self.assertEqual(res["error"], "no_trusted_asset_in_any_redirect")
        self.assertIsNone(res["r2_url"])
        self.assertIsNone(res["google_url"])

    def test_non_hubcdn_input_is_refused_before_any_fetch(self):
        fetched = []
        recorder = HopRecorder({})
        res = fast_fetch.unwrap_hubcdn(
            "https://example.com/cloud/abc",
            _fetch=lambda u: fetched.append(u) or ("", ""), _hop=recorder)
        self.assertEqual(res["error"], "not_a_hubcdn_cloud_page")
        self.assertEqual(fetched, [], "the fetch edge must not be touched")

    def test_file_page_input_refuses_even_when_hops_would_succeed(self):
        # Guards the dispatch condition's URL-substring arm, which is broader
        # than the strict page predicate: a hubcdn row on /file/ must never be
        # walked as if it were a cloud page.
        res, _rec = self.unwrap(happy_hops(),
                                url="https://hubcdn.io/file/abc")
        self.assertEqual(res["error"], "not_a_hubcdn_cloud_page")
        self.assertFalse(res["ok"])

    def test_buttonless_page_reports_no_buttons(self):
        res, _rec = self.unwrap(happy_hops(), buttons=[])
        self.assertEqual(res["error"], "no_dl_trigger_buttons")

    def test_absent_cookies_send_no_cookie_header_at_all(self):
        # An empty `Cookie: ` header is a different request from none; the
        # gateway must not see one it never got.
        res, rec = self.unwrap(happy_hops(), cookies="")
        self.assertTrue(res["ok"], res)
        for headers in rec.headers:
            self.assertNotIn("Cookie", headers)

    def test_fetch_crash_is_reported_not_raised(self):
        def boom(url):
            raise OSError("gateway is having a day")
        res = fast_fetch.unwrap_hubcdn("https://hubcdn.io/cloud/abc",
                                       _fetch=boom, _hop=HopRecorder({}))
        self.assertFalse(res["ok"])
        self.assertTrue(res["error"].startswith("cloud_fetch_fail:"), res)

    def test_empty_page_is_reported(self):
        res = fast_fetch.unwrap_hubcdn("https://hubcdn.io/cloud/abc",
                                       _fetch=lambda u: ("", ""),
                                       _hop=HopRecorder({}))
        self.assertEqual(res["error"], "empty_cloud_page")


if __name__ == "__main__":
    unittest.main(verbosity=2)
