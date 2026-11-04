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
            # 50filebee-style prefix-mashed domains intentionally NO LONGER
            # match (strict SLD since order qoder14_repin item 3); if the
            # family really moves to those, domain_registry.json 'hosters'
            # overrides are the sanctioned way to bless them.
            ("https://new5.filebee.xyz/d/abc", "filebee"),
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
        # Re-pinned 2026-11-05 (crown order qoder14_repin item 1): the old
        # assertion here (hubcloud service + bridge URL == horizon A) pinned
        # THE DEFECT ITSELF — it has since been fixed to an AND rule
        # (trusted label AND direct-file host). The vocabularies are still
        # different axes — kind words vs horizon letters — and the hubcloud
        # kind-C/horizon-A reversal has collapsed into agreement: a bridge
        # is now capped B on BOTH sides. Storage gating remains the bool
        # predicates, never letters.
        bridge = "https://hubcloud.ist/drive/ABC"
        self.assertEqual(hc.classify(bridge).letter, "C")
        self.assertEqual(_rc._derive_category({"service": "hubcloud"}, bridge),
                         "B")
        self.assertFalse(hc.is_playable_category(bridge))
        self.assertFalse(hc.is_direct_file(bridge))


@unittest.skipUnless(HAS_RC, _RC_REASON)
class TestCategoryACrossCheckWithResolvedCache(unittest.TestCase):
    """Re-pinned 2026-11-05 to qoder12's AND rule (crown order
    qoder14_repin item 1). resolved_cache now mints horizon A only when
    BOTH hold: (1) the service label maps to direct_file in our
    _SERVICE_TABLE, and (2) the URL host classifies direct_file. Every
    expected value below carries a correctness verdict, not a copied
    output:

    * label + host agree -> A is CORRECT: two independent pieces of
      evidence for a 24h trust promise — the bar the hubcloud fail-open
      proved necessary.
    * shape-only (no label) -> B is CORRECT and the AND rule is NOT wrong
      for it: every real cache row is written from a resolve_live_source
      answer carrying download_sources.service, so a label-less URL is
      degenerate input; horizon A is a *cache trust claim*, distinct from
      the *host kind* claim (is_direct_file stays True for a bare
      pixeldrain.com/u/ link — only the horizon caps at the conservative
      6h, whose sole cost is an earlier pool re-verify).
    * label-only (trusted label, non-direct host) -> B is CORRECT: that is
      precisely the label-lie class (gd-mirror rows are iqsmart pages).

    The 14 rows the previous pin documented as URL-shape-only DISAGREE did
    not weaken: they were B with no label before and are B with no label
    now; with their true ledger label + true direct host they STRENGTHEN
    to A (a capability the old marker list had no way to earn for
    gofile/1fichier/megaup/hexload/desiupload-class hosts).
    """

    # (marker, real-world URL, ledger service label, resolved_cache answer, why)
    CROSS_CHECK = (
        ("pixeldrain.com", "https://pixeldrain.com/u/AbC", "pixeldrain", "A",
         "label+host agree"),
        ("drive.google.com",
         "https://drive.google.com/uc?export=download&id=1x",
         "google_cdn", "A", "label+host agree, byte path"),
        ("googleusercontent.com",
         "https://video-downloads.googleusercontent.com/abc", "google_cdn",
         "A", "label+host agree"),
        ("drive.usercontent.google.com",
         "https://drive.usercontent.google.com/download?id=1x", "google_cdn",
         "A", "label+host agree"),
        ("firebasestorage.googleapis.com",
         "https://firebasestorage.googleapis.com/v0/b/x/o/y", "google_cdn",
         "A", "label+host agree"),
        ("r2.dev", "https://pub-abc.r2.dev/movie.mp4", "fsl_r2", "A",
         "label+host agree"),
        ("r2.cloudflarestorage.com",
         "https://b.r2.cloudflarestorage.com/k?X-Amz=1", "fsl_r2", "A",
         "label+host agree"),
        ("cloudflarestorage.com", "https://b.cloudflarestorage.com/k",
         "fsl_r2", "A", "label+host agree"),
        ("fastdl.beer", "https://fastdl.beer/file/a/movie.mkv", "fastdl-beer",
         "A", "item-2 gap closed: without the fastdl-beer service spelling "
         "in _SERVICE_TABLE this row fell to B"),
        ("gofile.io", "https://gofile.io/d/abc", "gofile", "A",
         "label+host agree (was unreachable before the label was added)"),
        ("1fichier.com", "https://1fichier.com/?abc", "1fichier", "A",
         "label+host agree"),
        ("megaup.net", "https://megaup.net/abc", "megaup", "A",
         "label+host agree"),
        ("vikingfile.com", "https://vikingfile.com/f/abc", "vikingfile", "A",
         "label+host agree"),
        ("desiupload.co", "https://desiupload.co/abc", "desiupload", "A",
         "label+host agree"),
        ("hexload.com", "https://hexload.com/f-abc.html", "hexload", "A",
         "label+host agree"),
        ("dailyuploads.net", "https://dailyuploads.net/abc", "dailyuploads",
         "A", "label+host agree"),
        ("frdl.to", "https://frdl.to/abc", "frdl", "A", "label+host agree"),
        ("mega.nz", "https://mega.nz/file/abc#keyfrag", "mega", "B",
         "SHAPE-REJECTED (order qoder14_viewerA): mega downloads need the "
         "client-side fragment key, which never reaches the server — even "
         "label+host agreement must not earn the 24h horizon."),
    )

    # Degenerate single-evidence rows: each must cap at B, by verdict above.
    SINGLE_EVIDENCE_ROWS = (
        ("shape only (no service label)", {},
         "https://pixeldrain.com/u/AbC", "B"),
        ("shape only (no service label)", {},
         "https://pub-abc.r2.dev/movie.mp4", "B"),
        ("shape only (no service label)", {},
         "https://fastdl.beer/file/a/movie.mkv", "B"),
        ("shape only (no service label)", {},
         "https://firebasestorage.googleapis.com/v0/b/x/o/y", "B"),
        ("label only (host is not a direct file)", {"service": "pixeldrain"},
         "https://viewer.evil.tld/watch/x", "B"),
        ("label only (host is an embed player)", {"service": "fastdl"},
         "https://player.mixdrop.co/e/abc", "B"),
        ("impostor host buys nothing", {"service": "pixeldrain"},
         "https://pixeldrain.dev/u/AbC", "B"),
    )

    def test_every_category_a_marker_has_a_cross_check_row(self):
        markers_a = {marker for marker, category, _ in hc._HOST_TABLE
                     if category == hc.CATEGORY_DIRECT_FILE}
        covered = {name for name, _u, _s, _e, _w in self.CROSS_CHECK}
        self.assertEqual(markers_a, covered,
                         "a Category-A host was added without a "
                         "resolved_cache cross-check row")

    def test_label_and_host_agreement_mints_horizon_a(self):
        for name, url, service, expected, why in self.CROSS_CHECK:
            with self.subTest(name=name):
                # The label half is always trusted-kind (that is the row's
                # point); the URL half is shape-checked by qoder14_viewerA's
                # gate, so rows whose sample URL is a viewer/fragment shape
                # correctly cap at B despite label+host agreement.
                self.assertTrue(hc.is_direct_file("", service),
                                f"{name}: service {service!r} must map "
                                "direct_file in _SERVICE_TABLE")
                self.assertEqual(hc.is_direct_file(url), expected == "A",
                                 f"{name}: {why}")
                self.assertEqual(
                    _rc._derive_category({"service": service}, url), expected,
                    why)

    def test_single_evidence_never_mints_horizon_a(self):
        for why, data, url, expected in self.SINGLE_EVIDENCE_ROWS:
            with self.subTest(why=why, url=url):
                self.assertEqual(
                    _rc._derive_category(data, url), expected, why)

    def test_kind_claim_survives_the_horizon_cap(self):
        # The shape-only verdict must NOT have weakened the KIND side:
        # a bare pixeldrain.com link is still Category A for every caller
        # of the predicates; only the cache horizon is conservative.
        self.assertTrue(hc.is_direct_file("https://pixeldrain.com/u/AbC"))
        self.assertTrue(hc.is_playable_category(
            "https://fastdl.beer/file/a/movie.mkv"))


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
            # Dotted markers are registrable domains (host IS the marker);
            # bare-label markers match <label>.<any-tld> exactly.
            host = token if "." in token else f"{token}.test"
            url = f"https://{host}/x"
            with self.subTest(token=token):
                self.assertEqual(_ss.classify_href(url, kinds), kind)
                # and the authority agrees on the same URL
                self.assertEqual(hc.SITE_SCOUT_KINDS.get(
                    hc.classify(url).category), kind)

    def test_scout_substring_matcher_is_the_residual_loose_side(self):
        # DOCUMENTED, not fixed: site_scout.classify_href matches tokens as
        # substrings of the whole URL — a pre-existing, CI-pinned behaviour
        # of the scout. The authority is strict, so on an impostor host the
        # two deliberately diverge and the STRICT answer governs storage
        # (is_direct_file / is_playable_category). Tightening scout's matcher
        # semantics too would be a crown order against test_site_scout's
        # pinned cases, not a side effect of this file.
        impostor = "https://pixeldrain.com.attacker.tld/u/AbC"
        self.assertEqual(hc.classify(impostor).category, hc.CATEGORY_UNKNOWN)
        self.assertFalse(hc.is_direct_file(impostor))
        self.assertEqual(
            _ss.classify_href(impostor, _ss.build_kinds_map({})), "direct")

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


class TestAdversarialHostTrust(unittest.TestCase):
    """Crown order qoder14_repin item 3: substring host trust was the same
    class of hole as the hubcloud horizon bug, arriving from the other
    direction. The demanded impostors must NOT earn Category A — or any
    trust — while every legitimate subdomain of a trusted registrable
    domain still classifies."""

    def test_pixeldrain_impostors_are_not_category_a(self):
        for bad in (
            "https://pixeldrain.dev/u/AbC",
            "https://pixeldrain.dev/api/file/AbC?download",
            "https://xpixeldrain.com/u/AbC",
            "https://pixeldrain.com.attacker.tld/u/AbC",
            "https://notreallypixeldrain.net/u/AbC",
        ):
            with self.subTest(url=bad):
                c = hc.classify(bad)
                self.assertEqual(c.category, hc.CATEGORY_UNKNOWN, bad)
                self.assertFalse(hc.is_direct_file(bad))
                self.assertFalse(hc.is_playable_category(bad))
                self.assertFalse(hc.is_pixeldrain(bad))

    def test_trusted_pixeldrain_host_and_subdomains(self):
        for good in ("https://pixeldrain.com/u/AbC",
                     "https://api.pixeldrain.com/file/AbC"):
            with self.subTest(url=good):
                self.assertTrue(hc.is_pixeldrain(good))
                self.assertTrue(hc.is_direct_file(good))

    def test_impostor_page_is_not_rewritten_to_an_api_endpoint(self):
        url, headers = hc.prepare_request(
            "https://pixeldrain.dev/u/AbC",
            {"Referer": "https://multimovies.example/watch"})
        self.assertEqual(url, "https://pixeldrain.dev/u/AbC")
        self.assertEqual(headers.get("Referer"),
                         "https://multimovies.example/watch")

    def test_wrong_tld_on_strict_single_domain_hosts_classifies_unknown(self):
        # Deliberate conservatism: the docs prove exactly ONE registered
        # domain for these; an unexpected TLD is an unexpected service.
        for bad in ("https://gofile.xyz/d/abc", "https://megaup.com/x",
                    "https://1fichier.to/x", "https://drive.google.ru/x"):
            with self.subTest(url=bad):
                self.assertEqual(hc.classify(bad).category,
                                 hc.CATEGORY_UNKNOWN)

    def test_tld_rotating_families_match_any_tld_on_the_exact_label(self):
        for good, category in (
            ("https://hubcloud.foo/drive/x", hc.CATEGORY_BRIDGE),
            ("https://vidly.io/embed/x", hc.CATEGORY_HLS_EMBED),
            ("https://bingr.pw/e/x", hc.CATEGORY_HLS_EMBED),
            ("https://new5.filebee.xyz/d/x", hc.CATEGORY_BRIDGE),
            ("https://embed.vidrift.net/api/orion/master.m3u8",
             hc.CATEGORY_HLS_EMBED),
            ("https://rozgarlelo.modiplay.xyz/embed/tmdb/movie?id=1",
             hc.CATEGORY_HLS_EMBED),
        ):
            with self.subTest(url=good):
                self.assertEqual(hc.classify(good).category, category)
        for bad in ("https://xhubcloud.ist/drive/x",
                    "https://hubcloud.com.attacker.tld/f/x",
                    "https://evil-hubcloud.ist/f/x",
                    "https://notvidrift.net/x"):
            with self.subTest(rejected=bad):
                self.assertEqual(hc.classify(bad).category,
                                 hc.CATEGORY_UNKNOWN)

    def test_marker_names_are_all_valid_host_shapes(self):
        for marker, _cat, _be in hc._HOST_TABLE:
            with self.subTest(marker=marker):
                self.assertNotIn("/", marker)
                self.assertFalse(marker.startswith("."))


class TestServiceLabelSpellings(unittest.TestCase):
    """Order qoder14_repin item 2: the label spellings the ledger writes must
    map to the same kind the host table gives — or single-evidence AND rows
    fall to the conservative cap for no reason."""

    def test_fastdl_beer_spelling_closes_the_gap(self):
        for label in ("fastdl-beer", "fastdl"):
            with self.subTest(label=label):
                self.assertTrue(hc.is_direct_file("", service=label))

    def test_classic_file_host_label_spellings_map_direct(self):
        for label in ("gofile", "1fichier", "megaup", "vikingfile",
                      "desiupload", "hexload", "dailyuploads", "frdl",
                      "mega", "pixeldrain", "fsl_r2", "google_cdn"):
            with self.subTest(label=label):
                self.assertTrue(hc.is_direct_file("", service=label))

    def test_no_service_label_maps_bridge_to_direct_or_vice_versa(self):
        for label, expect in (("hubcloud", hc.CATEGORY_BRIDGE),
                              ("hubcloud_10g", hc.CATEGORY_BRIDGE),
                              ("vegadrive", hc.CATEGORY_BRIDGE),
                              ("cineverse", hc.CATEGORY_HLS_EMBED),
                              ("gd-mirror", hc.CATEGORY_HLS_EMBED)):
            with self.subTest(label=label):
                c = hc.classify("", service=label)
                self.assertEqual(c.category, expect)


@unittest.skipUnless(HAS_RC, _RC_REASON)
class TestViewerShapeGate(unittest.TestCase):
    """CROWN ORDER qoder14_viewerA (2026-11-05).

    Volume named explicitly (test 5): this gate governs the two families
    measured in the coverage pass — google_cdn 116,604 links + mega 68,502
    links = 185,106 rows. Before the gate, ``drive…/file/d/x/view`` and
    ``mega.nz/file/x#key`` passed is_direct_file, banked horizon A (24 h)
    and were offered as kind='file' by /api/v1/download — the same class as
    the hubcloud HIGH defect, ~185k links instead of one family. If someone
    re-widens the gate, THESE subTests go red before that can miscache again.
    """

    VIEWER = "https://drive.google.com/file/d/1abc/view"
    MEGA_KEY = "https://mega.nz/file/AbCd#AESkeymaterial"
    PIXELDRAIN_REAL = "https://pixeldrain.com/u/abc123"
    EXT_REAL = "https://pub-abc.r2.dev/movies/folder/clip.mp4"

    def test_viewer_paths_rejected(self):
        for url in (self.VIEWER,
                    "https://drive.google.com/open?id=x&foo=bar#frag",
                    "https://drive.google.com/folderview?id=x",
                    "https://drive.google.com/fileview/x",
                    "https://docs.google.com/preview/x"):
            with self.subTest(url=url):
                self.assertFalse(hc.is_direct_file(url))
                self.assertFalse(hc.is_direct_file(url, "google_cdn"))

    def test_any_fragment_rejected_on_any_host(self):
        for url in (self.MEGA_KEY, self.PIXELDRAIN_REAL + "#note",
                    "https://pub-abc.r2.dev/movie.mp4#t=0,60"):
            with self.subTest(url=url):
                self.assertFalse(hc.is_direct_file(url))

    def test_mega_never_replayable_shape(self):
        self.assertFalse(hc.is_direct_file("https://mega.nz/file/AbCd"))
        # KIND stays honest: the host letter is still A for callers that ask
        # "what family is this" — only the byte-replay predicate says False.
        self.assertEqual(hc.classify("https://mega.nz/file/AbCd#k").category,
                         hc.CATEGORY_DIRECT_FILE)

    def test_real_direct_files_STILL_pass_the_gate(self):
        # Regression the other way (order: "I will reject a fix that
        # downgrades everything to B"): genuine byte GETs keep A.
        self.assertTrue(hc.is_direct_file(self.PIXELDRAIN_REAL))
        self.assertTrue(hc.is_direct_file(
            "https://drive.google.com/uc?export=download&id=1abc"))
        self.assertTrue(hc.is_direct_file(
            "https://video-downloads.googleusercontent.com/ADGPM2abc"))
        # Object-storage hosts are NOT page-capable: /folder//preview/ as an
        # object key must not be penalised (measured blowback when the rule
        # was host-agnostic).
        self.assertTrue(hc.is_direct_file(self.EXT_REAL))
        self.assertTrue(hc.is_direct_file(
            "https://x.r2.cloudflarestorage.com/preview/a.mp4"))
        # Label-only checks (the service half of the AND rule) see no URL
        # shape and must keep passing.
        self.assertTrue(hc.is_direct_file("", "google_cdn"))
        self.assertTrue(hc.is_direct_file("", "mega"))

    def _bank(self, conn, link_id, url, service, now):
        _rc.record_resolved_cache(conn, link_id,
                                  {"url": url, "service": service},
                                  now=now)
        return conn.execute(
            "SELECT category, reverify_after - resolved_at AS horizon, "
            "kind, url FROM resolved_cache WHERE link_id = ?",
            (link_id,)).fetchone()

    def test_horizon_deltas_measured_not_just_letters(self):
        # Assert the ACTUAL reverify_after delta (order item 2), not letters.
        import sqlite3 as _sql
        import time as _t
        conn = _sql.connect(":memory:")
        self.addCleanup(conn.close)
        _rc.init_resolved_cache(conn)
        now = _t.time()
        v = self._bank(conn, 1, self.VIEWER, "google_cdn", now)
        self.assertEqual(v[0], "B")
        self.assertLess(v[1], 7 * 3600, "viewer page must sit on the ~6h cap")
        self.assertGreater(v[1], 5 * 3600)
        m = self._bank(conn, 2, self.MEGA_KEY, "mega", now)
        self.assertEqual(m[0], "B")
        self.assertLess(m[1], 7 * 3600)
        p = self._bank(conn, 3, self.PIXELDRAIN_REAL, "pixeldrain", now)
        self.assertEqual(p[0], "A")
        self.assertGreater(p[1], 23 * 3600,
                           "a real direct file must keep the 24h horizon")
        self.assertLessEqual(p[1], 24 * 3600)

    def test_download_gate_refuses_viewer_shaped_rows(self):
        # Route-level in the sense the route decides: /api/v1/download calls
        # lookup_cache(want="download"), whose SQL requires kind='file'.
        # The HORIZON half (B/6h) works today; the KIND half is qoder12's
        # _derive_kind change (handed to crown) — until that lands, a
        # viewer row is still kind='file' and the gate lets it through, so
        # this is marked expectedFailure ON PURPOSE. Remove the marker when
        # the handoff lands; its XPASS is the acceptance signal.
        self.skipTest("covered by test_kind_gate_expectations below")

    def test_kind_gate_expectations(self):
        # THE HANDOFF ASSERTIONS (resolved_cache._derive_kind + fragment
        # handling — qoder12's file, NOT edited here):
        # MARKER REMOVED 2026-11-05: the handoff landed (task #24). It XPASSed
        # first, exactly as the comment predicted — that was the acceptance
        # signal, confirmed by the Crown Prince in the task order.
        import sqlite3 as _sql
        import time as _t
        conn = _sql.connect(":memory:")
        self.addCleanup(conn.close)
        _rc.init_resolved_cache(conn)
        now = _t.time()
        v = self._bank(conn, 10, self.VIEWER, "google_cdn", now)
        self.assertNotEqual(v[2], "file",
                            "an HTML viewer page is not a single-file "
                            "download candidate (order qoder14_viewerA #2)")
        m = self._bank(conn, 11, self.MEGA_KEY, "mega", now)
        self.assertNotEqual(m[2], "file")
        self.assertNotIn("#", m[3],
                         "fragment (mega key) must never be handed out in a "
                         "banked/public play_url (order item 3)")
        hit = _rc.lookup_cache(conn, 10, "download", now=now)
        self.assertIsNone(hit,
                          "/api/v1/download's own gate: a viewer-shaped row "
                          "must not answer the download route")
        # and the real file still passes the same route gate:
        real = self._bank(conn, 12, self.PIXELDRAIN_REAL, "pixeldrain", now)
        self.assertEqual(real[2], "file")
        self.assertIsNotNone(_rc.lookup_cache(conn, 12, "download", now=now))


if __name__ == "__main__":
    unittest.main(verbosity=2)
