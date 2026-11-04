#!/usr/bin/env python3
"""
Fast_Fetch/test_host_classifier.py — offline tests for host_classifier.py.

Every expected value is traceable to a statement in
docs-backup/radd-stream-host-knowledge/ (host-power-weakness.md, vidrift.md,
modiplay.md, iqsmart.md) or to the measured PixelDrain `hotlink_detected`
failure of 2026-11-04. No network, stdlib only.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import host_classifier as hc


class TestCategoryA(unittest.TestCase):
    """Category A — direct file hosts."""

    def test_pixeldrain_page(self):
        c = hc.classify("https://pixeldrain.com/u/AbC_123-x")
        self.assertEqual(c.category, hc.CATEGORY_DIRECT_FILE)
        self.assertEqual(c.letter, "A")
        self.assertEqual(c.backend, "pixeldrain")
        self.assertEqual(c.source, "host")

    def test_pixeldrain_api_link_still_direct(self):
        c = hc.classify("https://pixeldrain.com/api/file/AbC123")
        self.assertEqual(c.category, hc.CATEGORY_DIRECT_FILE)

    def test_gdrive_family(self):
        for url in (
            "https://drive.google.com/file/d/1AbC/view",
            "https://drive.usercontent.google.com/download?id=1AbC",
            "https://video-downloads.googleusercontent.com/abc",
            "https://firebasestorage.googleapis.com/v0/b/x/o/y",
        ):
            with self.subTest(url=url):
                c = hc.classify(url)
                self.assertEqual(c.category, hc.CATEGORY_DIRECT_FILE)
                self.assertEqual(c.backend, "gdrive")

    def test_r2_hosts(self):
        for url in (
            "https://pub-abc.r2.dev/movie.mp4",
            "https://bucket.r2.cloudflarestorage.com/key?X-Amz-Signature=x",
        ):
            with self.subTest(url=url):
                self.assertEqual(hc.classify(url).letter, "A")

    def test_fastdl_beer_is_direct_but_other_fastdl_is_not_claimed(self):
        self.assertEqual(
            hc.classify("https://fastdl.beer/file/abc/movie.mkv").letter, "A")
        # fastdlserver.site was measured dead-404; the family is SPLIT, so an
        # unrecognised fastdl domain must not be auto-blessed as direct.
        c = hc.classify("https://fastdlserver.site/f/abc")
        self.assertNotEqual(c.category, hc.CATEGORY_DIRECT_FILE)

    def test_gofile_and_classic_hosts(self):
        for url, backend in (
            ("https://gofile.io/d/abc", "gofile"),
            ("https://1fichier.com/?abc", "1fichier"),
            ("https://mega.nz/file/abc", "mega"),
        ):
            with self.subTest(url=url):
                c = hc.classify(url)
                self.assertEqual(c.category, hc.CATEGORY_DIRECT_FILE)
                self.assertEqual(c.backend, backend)


class TestCategoryB(unittest.TestCase):
    """Category B — HLS stream embeds."""

    def test_vidrift_movie_and_series_embeds(self):
        for url in (
            "https://embed.vidrift.net/embed/movie/533444",
            "https://embed.vidrift.net/embed/tv/91996/1/2",
        ):
            with self.subTest(url=url):
                c = hc.classify(url)
                self.assertEqual(c.category, hc.CATEGORY_HLS_EMBED)
                self.assertEqual(c.letter, "B")
                self.assertEqual(c.backend, "vidrift")

    def test_vidrift_master_playlist(self):
        c = hc.classify("https://embed.vidrift.net/api/orion/master.m3u8")
        self.assertEqual(c.backend, "vidrift")

    def test_streamhg_family(self):
        for url in (
            "https://hanerix.com/e/abc123",
            "https://vibuxer.com/e/abc123",
            "https://player.streamhg.cc/x",
        ):
            with self.subTest(url=url):
                c = hc.classify(url)
                self.assertEqual(c.category, hc.CATEGORY_HLS_EMBED)
                self.assertEqual(c.backend, "streamhg")

    def test_iqsmart_is_streamhg_backend(self):
        # iqsmart's proven chain terminates at hanerix/StreamHG.
        c = hc.classify("https://streams.iqsmartgames.com/embed/movie/123")
        self.assertEqual(c.category, hc.CATEGORY_HLS_EMBED)
        self.assertEqual(c.backend, "streamhg")

    def test_modiplay_front_end(self):
        c = hc.classify(
            "https://rozgarlelo.modiplay.xyz/embed/tmdb/movie?id=533444")
        self.assertEqual(c.category, hc.CATEGORY_HLS_EMBED)
        self.assertEqual(c.backend, "modiplay")

    def test_vidly_and_filmu(self):
        self.assertEqual(hc.classify("https://vidly.life/embed.ashx?x").backend,
                         "vidly")
        self.assertEqual(hc.classify("https://filmu.xyz/watch/abc").backend,
                         "vidly")

    def test_embed_player_families(self):
        for url, backend in (
            ("https://streamtape.com/v/abc", "streamtape"),
            ("https://mixdrop.co/e/abc", "mixdrop"),
            ("https://dood.lat/f/abc", "dood"),
            ("https://vidmoly.to/embed-abc.html", "vidmoly"),
        ):
            with self.subTest(url=url):
                c = hc.classify(url)
                self.assertEqual(c.category, hc.CATEGORY_HLS_EMBED)
                self.assertEqual(c.backend, backend)


class TestCategoryC(unittest.TestCase):
    """Category C — bridges needing unwrapping."""

    def test_bridge_family(self):
        cases = (
            ("https://hubcloud.ist/drive/ABC123", "hubcloud"),
            ("https://hubdrive.vip/f/abc", "hubcloud"),
            ("https://nexdrive.site/abc", "nexdrive"),
            ("https://mobilejsr.us/gate/abc", "mobilejsr"),
            ("https://linkszilla.com/abc", "linkszilla"),
            ("https://10moviesz.win/gate/abc", "shortener"),
            ("https://greenmotors.land/x", "greenmotors"),
            ("https://linkrit.pro/x", "greenmotors"),
            ("https://gdflix.to/d/abc", "gdflix"),
            ("https://filebee.xyz/d/abc", "filebee"),
            ("https://50filebee.xyz/d/abc", "filebee"),
            ("https://filepress.to/d/abc", "filebee"),
            ("https://vegadrive.xyz/f/abc", "vegadrive"),
            ("https://direct-cloud.to/x", "direct-cloud"),
            ("https://vcloud.vote/embed-abc", "vcloud"),
        )
        for url, backend in cases:
            with self.subTest(url=url):
                c = hc.classify(url)
                self.assertEqual(c.category, hc.CATEGORY_BRIDGE, url)
                self.assertEqual(c.letter, "C")
                self.assertEqual(c.backend, backend)

    def test_direct_cloud_not_swallowed_by_r2_cloud_marker(self):
        c = hc.classify("https://direct-cloud.to/file/abc")
        self.assertEqual(c.category, hc.CATEGORY_BRIDGE)


class TestLabelsLie(unittest.TestCase):
    """Classify by link host, never by service label."""

    def test_gd_mirror_label_over_iqsmart_host(self):
        # ~87,700 multimovies rows labelled gd-mirror/gdmirror are iqsmart
        # watch pages. The host must win.
        c = hc.classify("https://streams.iqsmartgames.com/embed/movie/9",
                        service="gd-mirror")
        self.assertEqual(c.source, "host")
        self.assertEqual(c.backend, "streamhg")
        self.assertEqual(c.category, hc.CATEGORY_HLS_EMBED)

    def test_cineverse_label_over_vidrift_host(self):
        # A modiplay (Cineverse) row whose saved link is the vidrift embed is
        # a vidrift copy, not an independent Modiplay backup.
        c = hc.classify("https://embed.vidrift.net/embed/movie/533444",
                        service="cineverse")
        self.assertEqual(c.backend, "vidrift")

    def test_backend_of_gives_one_dedup_key(self):
        modiplay_bingr = hc.backend_of("https://embed.vidrift.net/embed/movie/1")
        direct_vidrift = hc.backend_of(
            "https://rozgarlelo.modiplay.xyz/embed/tmdb/movie?id=1",
            service="cineverse")
        self.assertEqual(modiplay_bingr, "vidrift")
        self.assertEqual(direct_vidrift, "modiplay")

    def test_label_used_only_without_host_evidence(self):
        c = hc.classify("", service="cineverse")
        self.assertEqual(c.source, "label")
        self.assertEqual(c.category, hc.CATEGORY_HLS_EMBED)
        self.assertEqual(c.backend, "modiplay")

    def test_unknown_host_and_label(self):
        c = hc.classify("https://some-unknown-host.example/x", service="weird")
        self.assertEqual(c.category, hc.CATEGORY_UNKNOWN)
        self.assertEqual(c.letter, "?")


class TestPixelDrainHeaderFix(unittest.TestCase):
    """The measured 2026-11-04 failure: `hotlink_detected` without correct
    headers. Fix = direct /api/file/ endpoint + foreign Referer/Origin gone."""

    def test_page_url_rewritten_to_api_endpoint(self):
        for shape, fid in (("/u/AbC123", "AbC123"), ("/d/AbC123", "AbC123"),
                           ("/api/file/AbC123", "AbC123")):
            url, headers = hc.prepare_request(
                f"https://pixeldrain.com{shape}",
                {"Referer": "https://multimovies.example/watch/x",
                 "Origin": "https://multimovies.example"})
            with self.subTest(shape=shape):
                self.assertEqual(url, "https://pixeldrain.com/api/file/AbC123")
                self.assertNotIn("Referer", headers)
                self.assertNotIn("Origin", headers)
                self.assertTrue(all(k.lower() not in ("referer", "origin")
                                    for k in headers))

    def test_foreign_referer_stripped_case_insensitively(self):
        url, headers = hc.prepare_request(
            "https://pixeldrain.com/u/X1",
            {"referer": "https://evil.example/", "USER-AGENT": "RaddPlayer/1"})
        self.assertTrue(all(k.lower() != "referer" for k in headers))
        self.assertEqual(headers.get("USER-AGENT"), "RaddPlayer/1")

    def test_pixeldrain_own_referer_is_kept(self):
        _url, headers = hc.prepare_request(
            "https://pixeldrain.com/api/file/X1",
            {"Referer": "https://pixeldrain.com/u/X1"})
        self.assertEqual(headers.get("Referer"), "https://pixeldrain.com/u/X1")

    def test_caller_dict_not_mutated(self):
        original = {"Referer": "https://other.example/"}
        hc.prepare_request("https://pixeldrain.com/u/X1", original)
        self.assertEqual(original, {"Referer": "https://other.example/"})

    def test_non_id_page_url_left_alone_but_referer_still_stripped(self):
        url, headers = hc.prepare_request(
            "https://pixeldrain.com/l/someSharedList",
            {"Referer": "https://other.example/"})
        self.assertEqual(url, "https://pixeldrain.com/l/someSharedList")
        self.assertNotIn("Referer", headers)

    def test_strip_hotlink_headers_helper(self):
        out = hc.strip_hotlink_headers(
            {"Origin": "https://a.example", "X-Keep": "1"})
        self.assertEqual(out, {"X-Keep": "1"})

    def test_file_id_extraction(self):
        self.assertEqual(hc.pixeldrain_file_id("https://pixeldrain.com/u/Ab1"),
                         "Ab1")
        self.assertIsNone(hc.pixeldrain_file_id("https://pixeldrain.com/l/Ab1"))
        self.assertIsNone(hc.pixeldrain_file_id(""))


class TestVidriftRefererRule(unittest.TestCase):
    """vidrift.md hard rule: master fetch without
    Referer: embed.vidrift.net answers 403."""

    def test_referer_forced_on_vidrift_fetch(self):
        url, headers = hc.prepare_request(
            "https://embed.vidrift.net/api/orion/master.m3u8",
            {"Referer": "https://rozgarlelo.modiplay.xyz/"})
        self.assertEqual(headers["Referer"], "https://embed.vidrift.net/")

    def test_referer_added_when_absent(self):
        _url, headers = hc.prepare_request(
            "https://embed.vidrift.net/embed/movie/533444")
        self.assertEqual(headers["Referer"], "https://embed.vidrift.net/")

    def test_bingr_front_end_link_gets_vidrift_referer(self):
        _url, headers = hc.prepare_request("https://bingr.xyz/e/abc")
        self.assertEqual(headers["Referer"], "https://embed.vidrift.net/")

    def test_other_backends_get_no_invented_referer(self):
        _url, headers = hc.prepare_request(
            "https://hanerix.com/e/abc")
        self.assertNotIn("Referer", headers)


class TestMalformedInput(unittest.TestCase):
    def test_empty_and_junk_urls_do_not_crash(self):
        for bad in ("", None, "not a url", "://", "https://"):
            with self.subTest(bad=bad):
                c = hc.classify(bad)
                self.assertIn(c.category, (hc.CATEGORY_UNKNOWN,))

    def test_unknown_scheme_is_not_direct(self):
        c = hc.classify("magnet:?xt=urn:btih:abc")
        self.assertEqual(c.category, hc.CATEGORY_UNKNOWN)


if __name__ == "__main__":
    unittest.main(verbosity=2)
