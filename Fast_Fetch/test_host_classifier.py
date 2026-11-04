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

# resolved_cache is qoder12's uncommitted Phase-1 work in this lane. The
# cross-check below only runs where the module exists; the rest of the suite
# must not depend on it.
try:
    import resolved_cache as _rc
except ImportError:  # pragma: no cover - absent on master
    _rc = None
    _RC_REASON = "resolved_cache.py not present in this tree"
else:
    _RC_REASON = ""

HAS_RC = _rc is not None

try:
    import site_scout as _ss
except ImportError:  # pragma: no cover
    _ss = None
    _SS_REASON = "site_scout.py not importable"
else:
    _SS_REASON = ""

HAS_SS = _ss is not None


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


class TestStoragePredicates(unittest.TestCase):
    """Ruling item 2: explicit predicates, False for bridge and unknown, so a
    bridge/HTML landing page can never be stored as a cached playable row."""

    def test_is_direct_file(self):
        self.assertTrue(hc.is_direct_file("https://pixeldrain.com/u/AbC"))
        self.assertTrue(hc.is_direct_file("https://pub-x.r2.dev/movie.mp4"))
        self.assertFalse(hc.is_direct_file(
            "https://embed.vidrift.net/embed/movie/1"))
        self.assertFalse(hc.is_direct_file("https://hubcloud.ist/drive/X"))
        self.assertFalse(hc.is_direct_file("https://who-knows.example/x"))

    def test_is_playable_category_true_for_A_and_B(self):
        for url in (
            "https://pixeldrain.com/u/AbC",
            "https://embed.vidrift.net/embed/movie/1",
            "https://rozgarlelo.modiplay.xyz/embed/tmdb/movie?id=1",
            "https://hanerix.com/e/abc",
        ):
            with self.subTest(url=url):
                self.assertTrue(hc.is_playable_category(url))

    def test_is_playable_category_false_for_bridge_and_unknown(self):
        for url in (
            "https://hubcloud.ist/drive/ABC",
            "https://nexdrive.site/abc",
            "https://mobilejsr.us/gate/abc",
            "https://gdflix.to/d/abc",
            "https://filebee.xyz/d/abc",
            "https://totally-unknown-host.example/movie",
            "magnet:?xt=urn:btih:abc",
            "",
        ):
            with self.subTest(url=url):
                self.assertFalse(hc.is_playable_category(url))

    def test_predicates_accept_classification_objects(self):
        c = hc.classify("https://hubcloud.ist/drive/ABC")
        self.assertFalse(hc.is_playable_category(c))
        self.assertFalse(hc.is_direct_file(c))
        self.assertTrue(hc.is_bridge_category(c))

    def test_predicates_honour_service_label_fallback(self):
        self.assertTrue(hc.is_direct_file("", service="pixeldrain"))
        self.assertFalse(hc.is_bridge_category("", service="cineverse"))
        self.assertTrue(hc.is_bridge_category("", service="hubcloud"))

    def test_is_bridge_category_scoped_to_C(self):
        self.assertFalse(hc.is_bridge_category("https://pixeldrain.com/u/X"))
        self.assertFalse(hc.is_bridge_category("https://unknown.example/x"))


@unittest.skipUnless(HAS_RC, _RC_REASON)
class TestTaxonomyCollisionGuard(unittest.TestCase):
    """Ruling item 1: my CATEGORY_LABELS letters (host kind) and
    resolved_cache.category letters (cache horizon) are different systems.
    These tests prove the vocabularies cannot be conflated silently."""

    def test_host_kind_words_are_not_valid_cache_categories(self):
        import sqlite3

        conn = sqlite3.connect(":memory:")
        _rc.init_resolved_cache(conn)
        for value in (hc.CATEGORY_DIRECT_FILE, hc.CATEGORY_HLS_EMBED,
                      hc.CATEGORY_BRIDGE, hc.CATEGORY_UNKNOWN):
            with self.subTest(value=value):
                with self.assertRaises(sqlite3.IntegrityError):
                    conn.execute(
                        "INSERT INTO resolved_cache (link_id, url, category,"
                        " kind, resolved_at, reverify_after)"
                        " VALUES (1, 'https://x.test/a', ?, 'file', 0, 0)",
                        (value,))

    def test_kind_letters_are_not_horizon_letters(self):
        # A bare CATEGORY_LABELS "C"/"?" would be CHECK-rejected by the cache,
        # but "A"/"B" would pass through with the WRONG meaning — which is why
        # gating must use the bool predicates, never letters. hubcloud is the
        # sharpest case: host kind C (bridge) here, cache horizon A there,
        # because resolved_cache trusts the hubcloud *service* as a file
        # minteer. The predicates still refuse to treat the raw bridge page
        # as playable; that refusal is the storage gate, not the letter.
        bridge = "https://hubcloud.ist/drive/ABC"
        self.assertEqual(hc.classify(bridge).letter, "C")
        self.assertEqual(_rc._derive_category({"service": "hubcloud"}, bridge),
                         "A")
        self.assertFalse(hc.is_playable_category(bridge))
        self.assertFalse(hc.is_direct_file(bridge))


@unittest.skipUnless(HAS_RC, _RC_REASON)
class TestCategoryACrossCheckWithResolvedCache(unittest.TestCase):
    """Ruling item 3: for EVERY host in the Category-A table, pin what
    resolved_cache._derive_category returns on the same URL (no service
    label) and document each deliberate disagreement. Deliberate, because
    resolved_cache is qoder12's module and gets no behaviour change without
    a Crown-Prince ruling; its letters choose a freshness cap, ours name the
    host kind, and a classic file host the cache has never seen simply
    defaults to the conservative short-lived horizon B."""

    # (marker in _HOST_TABLE, real-world URL, resolved_cache's answer, why)
    CROSS_CHECK = (
        ("pixeldrain", "https://pixeldrain.com/u/AbC", "A", "agree"),
        ("drive.google", "https://drive.google.com/file/d/1x/view", "B",
         "DISAGREE: rc only trusts the google_cdn/gdmirror SERVICE label or "
         "the googleusercontent endpoint, never the bare drive.google host"),
        ("googleusercontent", "https://video-downloads.googleusercontent.com/abc",
         "B", "DISAGREE: no rc marker covers googleusercontent; needs "
         "service=google_cdn to reach horizon A"),
        ("drive.usercontent.google",
         "https://drive.usercontent.google.com/download?id=1x", "B",
         "DISAGREE: not in rc's marker list (fast_fetch's "
         "_DIRECT_MEDIA_HOSTS knows it, rc does not)"),
        ("firebasestorage.googleapis",
         "https://firebasestorage.googleapis.com/v0/b/x/o/y", "A",
         "agree — via rc's 'storage.googleapis' substring marker"),
        ("r2.dev", "https://pub-abc.r2.dev/movie.mp4", "A", "agree"),
        ("r2.cloudflarestorage",
         "https://b.r2.cloudflarestorage.com/k?X-Amz=1", "B",
         "DISAGREE: rc marks only 'r2.dev'; the cloudflarestorage endpoint "
         "is direct-file kind here but conservative horizon B there"),
        ("cloudflarestorage", "https://b.cloudflarestorage.com/k", "B",
         "DISAGREE: same reason as r2.cloudflarestorage"),
        ("fastdl.beer", "https://fastdl.beer/file/a/movie.mkv", "A",
         "agree — rc's 'fastdl' marker matches"),
        ("gofile", "https://gofile.io/d/abc", "B",
         "DISAGREE (documented by ruling): direct_file kind, horizon B"),
        ("1fichier", "https://1fichier.com/?abc", "B",
         "DISAGREE (documented by ruling): direct_file kind, horizon B"),
        ("megaup", "https://megaup.net/abc", "B",
         "DISAGREE (documented by ruling): direct_file kind, horizon B"),
        ("vikingfile", "https://vikingfile.com/f/abc", "B",
         "DISAGREE: direct_file kind, horizon B"),
        ("desiupload", "https://desiupload.co/abc", "B",
         "DISAGREE (documented by ruling): direct_file kind, horizon B"),
        ("hexload", "https://hexload.com/f-abc.html", "B",
         "DISAGREE (documented by ruling): direct_file kind, horizon B"),
        ("dailyuploads", "https://dailyuploads.net/abc", "B",
         "DISAGREE: direct_file kind, horizon B"),
        ("frdl", "https://frdl.to/abc", "B",
         "DISAGREE: direct_file kind, horizon B"),
        ("mega.nz", "https://mega.nz/file/abc", "B",
         "DISAGREE: direct_file kind, horizon B"),
    )

    def test_every_category_a_marker_has_a_cross_check_row(self):
        markers_a = {marker for marker, category, _ in hc._HOST_TABLE
                     if category == hc.CATEGORY_DIRECT_FILE}
        covered = {name for name, _url, _rc_exp, _why in self.CROSS_CHECK}
        self.assertEqual(markers_a, covered,
                         "a Category-A host was added without a "
                         "resolved_cache cross-check row")

    def test_cross_check_pinned_to_measured_behaviour(self):
        for name, url, expected_rc, why in self.CROSS_CHECK:
            with self.subTest(name=name):
                self.assertTrue(hc.is_direct_file(url),
                                f"{name} must be Category A kind")
                self.assertEqual(_rc._derive_category({}, url), expected_rc,
                                 f"{name}: {why}")

    def test_agree_and_disagree_split_is_accurate(self):
        disagreements = [row for row in self.CROSS_CHECK if row[2] != "A"]
        agreements = [row for row in self.CROSS_CHECK if row[2] == "A"]
        self.assertEqual(len(disagreements), 14)
        self.assertEqual(len(agreements), 4)


@unittest.skipUnless(HAS_SS, _SS_REASON)
class TestSiteScoutConsumesAuthority(unittest.TestCase):
    """Order qoder14 Task A: host_classifier is the single authority for
    hoster classification; site_scout consumes it, legacy rows are kept."""

    def test_authority_flag_is_live(self):
        self.assertEqual(_ss.HOSTER_AUTHORITY, "host_classifier")

    def test_authority_rows_lead_and_legacy_is_never_deleted(self):
        authority = hc.as_scout_hoster_kinds()
        merged = _ss.DEFAULT_HOSTER_KINDS
        self.assertEqual(merged[:len(authority)], authority)
        tail = merged[len(authority):]
        self.assertEqual(set(_ss._LEGACY_HOSTER_KINDS), set(tail),
                         "a legacy hoster row was deleted or altered — "
                         "AGENTS.md rule 4: extend, never remove")

    def test_every_authority_token_classifies_identically_in_scout(self):
        kinds = _ss.build_kinds_map({})
        for token, kind in hc.as_scout_hoster_kinds():
            url = f"https://{token}.test/x"
            with self.subTest(token=token):
                self.assertEqual(_ss.classify_href(url, kinds), kind)
                # and the authority agrees on the same URL
                self.assertEqual(hc.SITE_SCOUT_KINDS.get(
                    hc.classify(url).category), kind)

    def test_vcloud_semantic_disagreement_resolved_to_bridge(self):
        # host-power-weakness.md: "VCloud / VegaCloud | Bridge -> Generate
        # -> servers". The authority says bridge; the legacy embed row exists
        # but must never win.
        self.assertEqual(hc.classify("https://vcloud.vote/embed-x").category,
                         hc.CATEGORY_BRIDGE)
        self.assertEqual(
            _ss.classify_href("https://vcloud.vote/embed-x",
                              _ss.build_kinds_map({})), "bridge")
        self.assertIn(("vcloud", "embed"), _ss._LEGACY_HOSTER_KINDS)

    def test_fastdl_split_family(self):
        kinds = _ss.build_kinds_map({})
        # measured: fastdl.beer serves a direct MKV; the legacy generic
        # 'fastdl' -> embed row keeps the rest of the family classified.
        self.assertEqual(
            _ss.classify_href("https://fastdl.beer/file/a/movie.mkv", kinds),
            "direct")
        self.assertEqual(
            _ss.classify_href("https://fastdl.example.com/f/abc", kinds),
            "embed")

    def test_registry_overrides_still_outrank_the_authority(self):
        kinds = _ss.build_kinds_map({"hosters": {"vcloud": "embed"}})
        self.assertEqual(
            _ss.classify_href("https://vcloud.vote/embed-x", kinds), "embed")

    def test_scout_kind_vocabulary_matches_categories(self):
        self.assertEqual(hc.SITE_SCOUT_KINDS, {
            hc.CATEGORY_DIRECT_FILE: "direct",
            hc.CATEGORY_HLS_EMBED: "embed",
            hc.CATEGORY_BRIDGE: "bridge",
        })
        self.assertNotIn(hc.CATEGORY_UNKNOWN, hc.SITE_SCOUT_KINDS)

    def test_new_hosts_now_known_to_scout(self):
        # Hosts the order measured as host_classifier-only must classify.
        kinds = _ss.build_kinds_map({})
        for url, expected in (
            ("https://gofile.io/d/abc", "direct"),
            ("https://1fichier.com/?abc", "direct"),
            ("https://embed.vidrift.net/embed/movie/1", "embed"),
            ("https://rozgarlelo.modiplay.xyz/embed/tmdb/movie?id=1", "embed"),
            ("https://hanerix.com/e/abc", "embed"),
            ("https://gdflix.to/d/abc", "bridge"),
            ("https://bingr.xyz/e/abc", "embed"),
        ):
            with self.subTest(url=url):
                self.assertEqual(_ss.classify_href(url, kinds), expected)

    def test_unknown_hosts_stay_unknown_in_scout(self):
        # The CI-pinned sanity from test_site_scout must survive the merge:
        # authority tokens must not substring-collide with random paths.
        kinds = _ss.build_kinds_map({})
        for url in ("https://totally-unknown-xyz.example/a",
                    "https://randomhoster.example/file/xyz"):
            with self.subTest(url=url):
                self.assertEqual(_ss.classify_href(url, kinds), "unknown")


if __name__ == "__main__":
    unittest.main(verbosity=2)
