#!/usr/bin/env python3
"""
test_5movierulz_import.py — offline unit tests for the 5movierulz staging importer.

Every fixture below mirrors the markup verified live on 2026-10-28. No test makes
a network request: http_get / http_get_once are always patched.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import import_5movierulz as mr  # noqa: E402

BASE = mr.BASE_URL

MOVIE_URL = f"{BASE}/the-paradise-2026-hdrip-telugu-7626.html"
TAMIL_URL = f"{BASE}/the-paradise-2026-hdrip-tamil-7627.html"
SERIES_URL = f"{BASE}/bigg-boss-season-10-2026-hdrip-telugu-7448.html"
ADULT_URL = f"{BASE}/eyes-2026-hdrip-hindi-7001.html"
HDR_URL = f"{BASE}/hdr-test-2024-1080p-english-7002.html"

SYNOPSIS = ("The Savari, a tribe with no official recognition in India, lives in a place "
            "called Paradise. Adult themes are handled delicately.")

MAGNET_4K = (
    "magnet:?xt=urn:btih:CBC8931CA7975C9D0F9107B464CB4A99EBCF71A"
    "&amp;dn=www.5MovieRulz.company%20-%20The%20Paradise%20%282026%29%204K%20HQ"
    "%20WEB-DL%20-%20HEVC%20-%20%28DD%2B5.1%20%26%20AAC%29"
    "%20%5BTel%20%2B%20Tam%20%2B%20Hin%20%2B%20Mal%20%2B%20Kan%5D"
    "%20-%2027.3GB%20-%20ESub.mkv&amp;xl=29402467274")
MAGNET_1080 = (
    "magnet:?xt=urn:btih:7DEC0B3047FA06BEFF00A011060BC67D0718B905"
    "&amp;dn=www.5MovieRulz.company%20-%20The%20Paradise%20%282026%29"
    "%201080p%20HQ%20WEB-DL%20-%20AVC%20-%20AAC%20%5BTel%20%2B%20Tam%5D"
    "%20-%2010GB.mkv")
MAGNET_720 = (
    "magnet:?xt=urn:btih:3BE81E87E4B3283FB9067E1709C35173BAF4A8E8"
    "&amp;dn=www.5MovieRulz.company%20-%20The%20Paradise%20%282026%29"
    "%20720p%20WEB-DL%20-%20x264%20-%20AAC%20%5BTel%5D%20-%201.6GB.mkv")
MAGNET_480 = (
    "magnet:?xt=urn:btih:051FF08CED52C9C159EC8A20B6E1E55B535E7034"
    "&amp;dn=www.5MovieRulz.company%20-%20The%20Paradise%20%282026%29"
    "%20480p%20WEB-DL%20-%20AAC%20%5BTel%5D%20-%20450MB.mkv")
MAGNET_SERIES_1080 = (
    "magnet:?xt=urn:btih:1111111111111111111111111111111111111111"
    "&amp;dn=www.5MovieRulz.company%20-%20Bigg%20Boss%20Season%2010"
    "%20%282026%29%201080p%20HEVC%20-%202.5GB.mkv")
MAGNET_SERIES_720 = (
    "magnet:?xt=urn:btih:2222222222222222222222222222222222222222"
    "&amp;dn=www.5MovieRulz.company%20-%20Bigg%20Boss%20Season%2010"
    "%20%282026%29%20720p%20-%201GB.mkv")
MAGNET_SERIES_480 = (
    "magnet:?xt=urn:btih:3333333333333333333333333333333333333333"
    "&amp;dn=www.5MovieRulz.company%20-%20Bigg%20Boss%20Season%2010"
    "%20%282026%29%20480p%20-%20450MB.mkv")
MAGNET_HDR = (
    "magnet:?xt=urn:btih:4444444444444444444444444444444444444444"
    "&amp;dn=www.5MovieRulz.company%20-%20Format%20Test%20%282024%29"
    "%201080p%20HEVC%20HDR10%20-%202GB.mkv")
MAGNET_360 = (
    "magnet:?xt=urn:btih:5555555555555555555555555555555555555555"
    "&amp;dn=www.5MovieRulz.company%20-%20Format%20Test%20%282024%29"
    "%20360p%20AVC%20-%20400MB.mkv")

CARDS = """
<div class="mirror-link-card"><div class="source-badge">VERIFIED</div>
<a href="https://ww7.vcdnlare.com/v/
ADexglUCIwnKREi?sid=9481&amp;t=hls" class="stream-link-btn">
<span class="play-icon">▶</span><span class="platform-name">Streamlare</span></a></div>
<div class="mirror-link-card"><div class="source-badge">VERIFIED</div>
<a href="https://www.uperbox.cx/wGYT2hIz" class="stream-link-btn">
<span class="platform-name">Uperbox</span></a></div>
<div class="mirror-link-card"><div class="source-badge">VERIFIED</div>
<a href="https://www.easysyncr.me/BjouwLqX" class="stream-link-btn">
<span class="platform-name">Easysyncr</span></a></div>
<div class="mirror-link-card"><div class="source-badge">VERIFIED</div>
<a href="https://www.easysyncr.me/A5p8Hv3q" class="stream-link-btn">
<span class="platform-name">Download</span></a></div>
<div class="mirror-link-card"><div class="source-badge">VERIFIED</div>
<a href="https://hglink.to/dqyazgvajunf" class="stream-link-btn">
<span class="platform-name">Streamwish</span></a></div>
<div class="mirror-link-card"><div class="source-badge">VERIFIED</div>
<a href="https://minochinos.com/f/aaezcy3dxp82" class="stream-link-btn">
<span class="platform-name">Filelions</span></a></div>
"""

LOCATIONS = ('"https:\\/\\/streamvin.com\\/video\\/3a15c7d0", '
             '"https:\\/\\/ww7.vcdnlare.com\\/v\\/ADexglUCIwnKREi?sid=9481&amp;t=hls"')

SUBTITLE_BLOCK = """
<div class="subtitles-section">
<a href="/subs/the-paradise.en.vtt">English VTT</a>
<a href="https://cdn.example.com/subs/the-paradise.ta.srt">Tamil SRT</a>
<a href="/subs/the-paradise.ara.ass">Arabic ASS</a>
</div>
"""


def _info(label, value):
    return f'<p><strong>{label}:</strong> {value}</p>'


def _torrent(magnet, size):
    return ('<a href="' + magnet + '" class="torrent-btn" rel="nofollow">'
            '<span class="magnet-icon">🧲</span>'
            '<span class="btn-text">GET THIS TORRENT</span>'
            f'<span class="btn-size">{size}</span></a>')


def _page(title, info_html, torrent_html, cards_html, extra=""):
    return f"""<!DOCTYPE html><html><head>
<title>{title} | MovieRulz</title>
<meta property="og:title" content="{title}">
<meta property="og:image" content="{BASE}/uploads/poster.jpg">
<meta name="description" content="{SYNOPSIS}">
</head><body><article class="post-1 type-post">
<h2 class="entry-title">{title}</h2>
<div class="entry-content">
<div class="movie-poster-wrapper"><img src="{BASE}/uploads/poster.jpg"></div>
<div class="movie-info-section"><div class="movie-info-block">{info_html}</div></div>
<div class="synopsis-section">Synopsis<p>{SYNOPSIS}</p></div>
<script>var locations = [{LOCATIONS}];</script>
<div class="torrent-section"><h3>DOWNLOAD TORRENT FILES</h3>{torrent_html}</div>
<div class="streaming-section"><h3>STREAMING LINKS</h3>{cards_html}</div>
{extra}
</div></article></body></html>"""


MOVIE_INFO = "".join([
    _info("Directed by", '<a href="/director/srikanth-odela">Srikanth Odela</a>'),
    _info("Starring by", '<a href="/actor/nani">Nani</a>, <a href="/actor/keerthy">Keerthy Suresh</a>'),
    _info("Genres", '<a href="/genre/action">Action</a>, <a href="/genre/drama">Drama</a>'),
    _info("Categories", '<a href="/category/telugu-featured">Telugu Featured</a>'),
    _info("Country", "India"),
    _info("Language", "Telugu"),
    _info("Quality", "HDRip"),
])
MOVIE_TORRENTS = "".join([
    _torrent(MAGNET_4K, "27.3 gb 4k 2160p"),
    _torrent(MAGNET_1080, "10 gb 1080p"),
    _torrent(MAGNET_720, "1.6 gb 720p"),
    _torrent(MAGNET_480, "450 mb 480p"),
])
MOVIE_FIXTURE = _page("The Paradise (2026) HDRip [Telugu]", MOVIE_INFO,
                      MOVIE_TORRENTS, CARDS)
SUBTITLE_FIXTURE = _page("The Paradise (2026) HDRip [Telugu]", MOVIE_INFO,
                         MOVIE_TORRENTS, CARDS, extra=SUBTITLE_BLOCK)

SERIES_INFO = "".join([
    _info("Directed by", "Puri Jagannadh"),
    _info("Starring by", "Nagarjuna Akkineni"),
    _info("Genres", "Reality-TV"),
    _info("Categories", "Telugu Featured, Web Series"),
    _info("Country", "India"),
    _info("Language", "Telugu"),
    _info("Quality", "HDRip"),
])
SERIES_TORRENTS = "".join([
    _torrent(MAGNET_SERIES_1080, "2.5 gb 1080p [D-49]"),
    _torrent(MAGNET_SERIES_720, "1 gb 720p [D-49]"),
    _torrent(MAGNET_SERIES_480, "450 mb 480p [D-49]"),
])
SERIES_FIXTURE = _page("Bigg Boss Season 10 (2026) HDRip [Telugu]",
                       SERIES_INFO, SERIES_TORRENTS, CARDS)

ADULT_INFO = "".join([
    _info("Genres", "Erotic, Drama"),
    _info("Categories", "Hot Short Films"),
    _info("Language", "Hindi"),
])
ADULT_FIXTURE = _page("Eyes (2026) 18+ Hot Short Film [Hindi]", ADULT_INFO,
                      _torrent(MAGNET_720, "1.6 gb 720p"), CARDS)

HDR_INFO = "".join([
    _info("Genres", "Action"),
    _info("Language", "English"),
])
HDR_FIXTURE = _page(
    "Format Test (2024) 1080p HEVC HDR10 [English]", HDR_INFO,
    _torrent(MAGNET_HDR, "2 gb 1080p") + _torrent(MAGNET_360, "400 mb 360p"),
    "")

LISTING_PAGE1 = f"""<html><body>
<a href='{BASE}/the-paradise-2026-hdrip-telugu-7626.html' title="The Paradise">one</a>
<a href='{BASE}/418-2026-dvdscr-telugu-7649.html' title="418">two</a>
<a href='{BASE}/category/telugu-featured'>category</a>
<a href='{BASE}/year/2026/page/2'>2</a>
<a href='{BASE}/year/2026/page/62'>Last</a>
</body></html>"""
LISTING_PAGE2 = f"""<html><body>
<a href='{BASE}/bigg-boss-season-10-2026-hdrip-telugu-7448.html'>series</a>
</body></html>"""
HOMEPAGE_FIXTURE = (f"""<html><head><title>MovieRulz | Latest Telugu, Tamil, """
                    f"""Malayalam &amp; Hindi Movies</title>
<meta property="og:title" content="MovieRulz | Latest Telugu, Tamil, Malayalam Movies">
</head><body><h1>{BASE}</h1></body></html>""")


def _post(fixture=MOVIE_FIXTURE, url=MOVIE_URL):
    with mock.patch.object(mr, "http_get", return_value=(200, url, fixture)):
        return mr.parse_page(url)


class TestUrlHandling(unittest.TestCase):
    def test_newline_wrapped_hrefs_are_rejoined(self):
        self.assertEqual(
            mr.normalize_url("https://ww7.vcdnlare.com/v/\nADex"),
            "https://ww7.vcdnlare.com/v/ADex")

    def test_html_entities_are_decoded_before_quoting(self):
        self.assertEqual(
            mr.normalize_url("https://h.example/a?x=1&amp;y=2"),
            "https://h.example/a?x=1&y=2")

    def test_unicode_slugs_are_percent_quoted(self):
        got = mr.normalize_url(f"{BASE}/amor\u00e9-2026.html")
        self.assertIn("%C3%A9", got)
        self.assertEqual(mr.urllib.parse.urlsplit(got).hostname,
                         "www.5movierulz.green")


class TestTitleAndProvenance(unittest.TestCase):
    def test_movie_title_is_cleaned_of_packaging(self):
        got = mr.parse_title("The Paradise (2026) HDRip [Telugu]",
                             "the-paradise-2026-hdrip-telugu")
        self.assertEqual(got["clean_title"], "The Paradise")
        self.assertEqual(got["year"], 2026)
        self.assertEqual(got["media_type"], "movie")
        self.assertEqual(got["canonical_key"], "the-paradise-2026")

    def test_numeric_title_survives(self):
        got = mr.parse_title("418 (2026) DVDScr [Telugu]", "418-2026-dvdscr-telugu")
        self.assertEqual(got["clean_title"], "418")
        self.assertEqual(got["year"], 2026)

    def test_series_keeps_its_season_in_the_name(self):
        got = mr.parse_title("Bigg Boss Season 10 (2026) HDRip [Telugu]",
                             "bigg-boss-season-10-2026-hdrip-telugu")
        self.assertEqual(got["clean_title"], "Bigg Boss Season 10")
        self.assertEqual(got["season_number"], 10)
        self.assertEqual(got["media_type"], "series")
        self.assertEqual(got["canonical_key"], "bigg-boss-season-10-2026")

    def test_language_reprints_share_one_identity_key(self):
        a = mr.build_canonical_key("The Paradise", 2026, None, None,
                                   "the-paradise-2026-hdrip-telugu")
        b = mr.build_canonical_key("The Paradise", 2026, None, None,
                                   "the-paradise-2026-hdrip-tamil")
        self.assertEqual(a, b)

    def test_year_falls_back_to_the_slug(self):
        got = mr.parse_title("Some Untitled Rip", "some-title-2021-brrip-telugu")
        self.assertEqual(got["year"], 2021)

    def test_site_branding_never_reaches_a_display_string(self):
        self.assertEqual(mr.scrub_brand("www.5MovieRulz.company - The Paradise"),
                         "The Paradise")
        self.assertNotIn("rulz", mr.scrub_brand("MovieRulz").lower())
        got = mr.parse_title("www.5MovieRulz.company - The Paradise (2026) 4K",
                             "the-paradise-2026")
        self.assertEqual(got["clean_title"], "The Paradise")
        self.assertNotIn("rulz", got["clean_title"].lower())


class TestAdultFlagging(unittest.TestCase):
    def test_adult_labels_flag(self):
        self.assertTrue(mr.is_adult_content("Eyes (2026) 18+ Hot Short Film"))
        self.assertTrue(mr.is_adult_content("Some Film", "Hot Short Films"))
        self.assertTrue(mr.is_adult_content("Some Film", "", "Erotic, Drama"))

    def test_mainstream_labels_do_not_flag(self):
        self.assertFalse(mr.is_adult_content("The Paradise (2026)", "Action, Drama",
                                             "Telugu Movies 2026"))
        self.assertFalse(mr.is_adult_content("Bigg Boss Season 10", "Reality-TV"))

    def test_ambiguous_words_in_prose_do_not_hide_a_title(self):
        blurb = ("A bold, sensual story of lust and temptation with adult themes "
                 "handled delicately.")
        self.assertFalse(mr.is_adult_content("Dil Padosi", "Drama",
                                             prose=(blurb,)))
        self.assertTrue(mr.is_adult_content("Dil Padosi", "Adult, Drama"))


class TestQualityTiers(unittest.TestCase):
    def test_every_torrent_tier_is_a_release(self):
        post = _post()
        self.assertEqual([r["quality"] for r in post["releases"] if r["quality"]],
                         ["4K", "1080p", "720p", "480p"])
        self.assertEqual(post["releases"][-1]["label"], "Watch Online / Mirrors")

    def test_codec_and_size_come_from_the_magnet(self):
        releases = _post()["releases"]
        self.assertEqual(releases[0]["codec"], "HEVC")
        self.assertEqual(releases[1]["codec"], "AVC")
        self.assertEqual(releases[0]["size_bytes"], int(27.3 * 1024 ** 3))
        self.assertEqual(releases[3]["size_bytes"], int(450 * 1024 ** 2))

    def test_magnet_audio_tracks_are_read(self):
        first = _post()["releases"][0]
        self.assertEqual(first["audio_languages"],
                         "Telugu, Tamil, Hindi, Malayalam, Kannada")

    def test_hdr_and_360p_tokens_are_kept(self):
        post = _post(HDR_FIXTURE, HDR_URL)
        self.assertEqual([r["quality"] for r in post["releases"] if r["quality"]],
                         ["1080p", "360p"])
        self.assertEqual(post["releases"][0]["codec"], "HEVC")
        self.assertEqual(post["releases"][0]["hdr"], "HDR10")
        self.assertIn("HDR10", post["releases"][0]["label"])
        self.assertIn("HEVC", post["releases"][0]["label"])
        self.assertIsNone(post["releases"][1]["hdr"])

    def test_a_series_page_offers_its_own_tiers(self):
        post = _post(SERIES_FIXTURE, SERIES_URL)
        self.assertEqual([r["quality"] for r in post["releases"] if r["quality"]],
                         ["1080p", "720p", "480p"])
        self.assertEqual(post["content_type"], "series")
        self.assertEqual(json.loads(post["seasons"])[0]["season"], 10)


class TestParsePage(unittest.TestCase):
    def test_fixture_yields_a_staging_shaped_post(self):
        post = _post()
        self.assertEqual(post["clean_title"], "The Paradise")
        self.assertEqual(post["year"], 2026)
        self.assertEqual(post["source_site"], "5movierulz")
        self.assertEqual(post["genres"], "Action, Drama")
        self.assertEqual(post["cast_names"], "Nani, Keerthy Suresh")
        self.assertEqual(post["director"], "Srikanth Odela")
        self.assertEqual(post["languages"], "Telugu")
        self.assertEqual(post["is_18_plus"], 0)
        self.assertEqual(post["poster_url"], f"{BASE}/uploads/poster.jpg")
        self.assertEqual(post["content_type"], "movie")

    def test_adult_page_is_stored_and_flagged(self):
        post = _post(ADULT_FIXTURE, ADULT_URL)
        self.assertEqual(post["clean_title"], "Eyes")
        self.assertEqual(post["is_18_plus"], 1)

    def test_magnets_are_active_download_sources(self):
        post = _post()
        magnet = post["releases"][0]["sources"][0]
        self.assertEqual(magnet["service"], "torrent")
        self.assertEqual(magnet["status"], "active")
        self.assertEqual(magnet["playback_type"], "download")
        self.assertEqual(magnet["resource_id"], "CBC8931CA7975C9D0F9107B464CB4A99EBCF71A")

    def test_stream_cards_and_players_become_watch_sources(self):
        post = _post()
        watch = post["releases"][-1]
        self.assertEqual(watch["label"], "Watch Online / Mirrors")
        services = [s["service"] for s in watch["sources"]]
        self.assertEqual(len(services), 7)  # 6 cards + Streamvin; vcdnlare deduped
        self.assertIn("streamvin", services)
        self.assertIn("streamlare", services)
        self.assertEqual(services.count("easysyncr"), 2)
        self.assertTrue(all(s["status"] == "unknown" for s in watch["sources"]))
        temp = {s["service"]: s["is_temporary"] for s in watch["sources"]}
        self.assertEqual(temp["streamlare"], 1)  # ?sid=&t=hls session
        self.assertEqual(temp["streamvin"], 0)

    def test_download_labelled_mirror_is_recorded_as_download(self):
        watch = _post()["releases"][-1]
        by_url = {s["source_url"]: s for s in watch["sources"]}
        self.assertEqual(
            by_url["https://www.easysyncr.me/A5p8Hv3q"]["playback_type"], "download")

    def test_no_sitemap_fallback_is_not_a_post(self):
        with mock.patch.object(mr, "http_get") as get:
            self.assertIsNone(mr.parse_page(f"{BASE}/year/2026"))
        get.assert_not_called()

    def test_a_404_is_declined(self):
        with mock.patch.object(mr, "http_get", return_value=(404, MOVIE_URL, "")):
            self.assertIsNone(mr.parse_page(MOVIE_URL))

    def test_a_shelf_body_that_lands_on_a_post_url_is_declined(self):
        with mock.patch.object(mr, "http_get",
                               return_value=(200, f"{BASE}/", HOMEPAGE_FIXTURE)):
            self.assertEqual(mr._parse_page(MOVIE_URL)[1], "removed")


class TestSubtitles(unittest.TestCase):
    def test_each_published_subtitle_is_its_own_source_row(self):
        post = _post(SUBTITLE_FIXTURE)
        subs = [s for r in post["releases"] for s in r["sources"]
                if s["playback_type"] == "subtitle"]
        self.assertEqual(len(subs), 3)
        self.assertEqual({s["service"] for s in subs}, {"subtitle"})
        self.assertEqual({s["resource_id"].rsplit(".", 1)[-1] for s in subs},
                         {"vtt", "srt", "ass"})
        self.assertTrue(all(s["status"] == "active" for s in subs))

    def test_the_raw_subtitle_map_is_kept_in_raw_meta(self):
        post = _post(SUBTITLE_FIXTURE)
        raw = post["raw_meta"]["subtitles"]
        self.assertEqual(len(raw), 3)
        self.assertEqual([s["ext"] for s in raw], ["vtt", "srt", "ass"])

    def test_probing_skips_subtitle_rows(self):
        post = _post(SUBTITLE_FIXTURE)
        calls = []

        def ok(url, referer=None, timeout=25):
            calls.append(url)
            return 200, None, ""

        with mock.patch.object(mr, "http_get_once", side_effect=ok):
            mr.resolve_links(post, probe=True)
        self.assertEqual(len(calls), 7)
        self.assertFalse(any(".vtt" in u or ".srt" in u or ".ass" in u for u in calls))


class TestResolveLinks(unittest.TestCase):
    def test_probe_false_never_touches_the_network(self):
        post = _post()
        with mock.patch.object(mr, "http_get_once",
                               side_effect=AssertionError("network used")):
            mr.resolve_links(post, probe=False)
        watch = post["releases"][-1]
        self.assertTrue(all(s["status"] == "unknown" for s in watch["sources"]))
        self.assertTrue(all(s["last_checked"] is None for s in watch["sources"]))

    def test_a_dead_mirror_is_retained_with_status_dead(self):
        post = _post()
        before = sum(len(r["sources"]) for r in post["releases"])
        with mock.patch.object(mr, "http_get_once", return_value=(404, None, "")):
            mr.resolve_links(post, probe=True)
        after = sum(len(r["sources"]) for r in post["releases"])
        self.assertEqual(before, after)
        watch = post["releases"][-1]
        self.assertTrue(all(s["status"] == "dead" for s in watch["sources"]))
        self.assertTrue(all(s["final_url"] is None for s in watch["sources"]))
        self.assertTrue(all(s["status"] == "active" for s in post["releases"][0]["sources"]))

    def test_a_refused_mirror_is_blocked_not_dropped(self):
        post = _post()
        with mock.patch.object(mr, "http_get_once", return_value=(403, None, "")):
            mr.resolve_links(post, probe=True)
        self.assertTrue(all(s["status"] == "blocked"
                            for s in post["releases"][-1]["sources"]))
        self.assertEqual(len(post["releases"][-1]["sources"]), 7)

    def test_a_js_gate_is_recorded_as_js_required(self):
        post = _post()
        with mock.patch.object(mr, "http_get_once",
                               return_value=(200, None, "Just a moment...")):
            mr.resolve_links(post, probe=True)
        self.assertTrue(all(s["status"] == "js_required"
                            for s in post["releases"][-1]["sources"]))

    def test_a_live_mirror_is_active(self):
        post = _post()
        with mock.patch.object(mr, "http_get_once", return_value=(200, None, "ok")):
            mr.resolve_links(post, probe=True)
        self.assertTrue(all(s["status"] == "active"
                            for s in post["releases"][-1]["sources"]))


class TestSyncCatalog(unittest.TestCase):
    def setUp(self):
        self._years = (mr.FIRST_YEAR, mr.LAST_YEAR)
        mr.FIRST_YEAR = mr.LAST_YEAR = 2026
        self.db = Path(tempfile.mkdtemp()) / "5movierulz.db"

    def tearDown(self):
        mr.FIRST_YEAR, mr.LAST_YEAR = self._years

    def _get(self, url, timeout=30, retries=3):
        if url.endswith("/year/2026/page/2"):
            return 200, url, LISTING_PAGE2
        if url.endswith("/year/2026"):
            return 200, url, LISTING_PAGE1
        return 404, url, ""

    def test_year_shelves_are_followed_and_shelves_are_skipped(self):
        with mock.patch.object(mr, "http_get", side_effect=self._get):
            added = mr.sync_catalog(db_path=self.db, verbose=False)
        self.assertEqual(added, 3)
        conn = sqlite3.connect(self.db)
        locs = [r[0] for r in conn.execute("SELECT loc FROM sitemap_cache")]
        conn.close()
        self.assertTrue(all(mr.POST_PATH_RE.match(mr.urllib.parse.urlsplit(l).path)
                            for l in locs))
        self.assertNotIn(f"{BASE}/category/telugu-featured", locs)
        self.assertEqual(len(locs), 3)

    def test_limit_stops_the_enumeration(self):
        with mock.patch.object(mr, "http_get", side_effect=self._get) as get:
            added = mr.sync_catalog(limit=2, db_path=self.db, verbose=False)
        self.assertEqual(added, 2)
        self.assertEqual(get.call_count, 1)

    def test_a_dead_year_does_not_abort_the_run(self):
        mr.FIRST_YEAR = mr.LAST_YEAR = 2025
        with mock.patch.object(mr, "http_get", return_value=(404, "", "")):
            self.assertEqual(mr.sync_catalog(db_path=self.db, verbose=False), 0)

    def test_resync_does_not_reset_indexed_pages(self):
        with mock.patch.object(mr, "http_get", side_effect=self._get):
            mr.sync_catalog(db_path=self.db, verbose=False)
        conn = sqlite3.connect(self.db)
        conn.execute("UPDATE sitemap_cache SET scraped = 1")
        conn.commit()
        conn.close()
        with mock.patch.object(mr, "http_get", side_effect=self._get):
            self.assertEqual(mr.sync_catalog(db_path=self.db, verbose=False), 0)


class TestStagingDatabase(unittest.TestCase):
    def setUp(self):
        self.db = Path(tempfile.mkdtemp()) / "5movierulz.db"
        self.post = _post()

    def _count(self, table):
        conn = sqlite3.connect(self.db)
        try:
            return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        finally:
            conn.close()

    def test_writes_the_isolated_staging_file_only(self):
        out = mr.export_staging(self.db, [self.post])
        self.assertEqual(out["posts_written"], 1)
        self.assertEqual(out["releases_written"], 5)
        self.assertEqual(out["sources_written"], 11)
        self.assertTrue(self.db.exists())

    def test_recrawl_is_idempotent(self):
        mr.export_staging(self.db, [self.post])
        mr.export_staging(self.db, [self.post])
        self.assertEqual(self._count("posts"), 1)
        self.assertEqual(self._count("releases"), 5)
        self.assertEqual(self._count("sources"), 11)

    def test_two_language_pages_keep_their_own_prints(self):
        tamil = json.loads(json.dumps(self.post))
        tamil["url"] = TAMIL_URL
        for rel in tamil["releases"]:
            rel["origin_url"] = TAMIL_URL
        mr.export_staging(self.db, [self.post])
        mr.export_staging(self.db, [tamil])
        self.assertEqual(self._count("releases"), 10)
        conn = sqlite3.connect(self.db)
        self.assertEqual(conn.execute(
            "SELECT COUNT(DISTINCT origin_url) FROM releases").fetchone()[0], 2)
        conn.close()

    def test_subtitle_rows_are_persisted_with_their_map(self):
        mr.export_staging(self.db, [_post(SUBTITLE_FIXTURE)])
        conn = sqlite3.connect(self.db)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM sources WHERE playback_type = 'subtitle'").fetchall()
        raw = json.loads(conn.execute("SELECT raw_meta FROM posts").fetchone()[0])
        conn.close()
        self.assertEqual(len(rows), 3)
        self.assertEqual({r["service"] for r in rows}, {"subtitle"})
        self.assertEqual(len(raw["subtitles"]), 3)

    def test_source_columns_are_the_ones_the_catalog_reads(self):
        mr.export_staging(self.db, [self.post])
        conn = sqlite3.connect(self.db)
        cols = {c[1] for c in conn.execute("PRAGMA table_info(sources)")}
        conn.close()
        for needed in ("source_name", "service", "resource_id", "source_url",
                       "final_url", "playback_type", "is_temporary", "status"):
            self.assertIn(needed, cols)

    def test_no_provenance_token_reaches_a_display_column(self):
        mr.export_staging(self.db, [self.post])
        conn = sqlite3.connect(self.db)
        post = conn.execute("SELECT title, clean_title, synopsis, genres FROM posts").fetchone()
        labels = [r[0] for r in conn.execute("SELECT label FROM releases")]
        conn.close()
        joined = " ".join(str(v) for v in post).lower()
        joined += " " + " ".join(l.lower() for l in labels)
        for needle in ("rulz", "www.", "vcdnlare", "minochinos", "hglink", "5movie"):
            self.assertNotIn(needle, joined)

    def test_adult_flag_is_set_at_storage_time(self):
        mr.export_staging(self.db, [_post(ADULT_FIXTURE, ADULT_URL)])
        conn = sqlite3.connect(self.db)
        self.assertEqual(conn.execute(
            "SELECT is_18_plus FROM posts").fetchone()[0], 1)
        conn.close()

    def test_stats_and_status_counts(self):
        mr.export_staging(self.db, [self.post])
        st = mr.get_stats(self.db)
        self.assertEqual(st["posts"], 1)
        self.assertEqual(st["releases"], 5)
        self.assertEqual(st["sources"], 11)
        self.assertEqual(st["subtitles"], 0)
        self.assertEqual(st["adult_flagged"], 0)
        self.assertEqual(st["source_status"], {"active": 4, "unknown": 7})
        self.assertEqual(st["content_types"], {"movie": 1})
        self.assertEqual(st["services"]["torrent"], 4)

    def test_a_post_without_tiers_is_skipped(self):
        empty = dict(self.post, releases=[])
        out = mr.export_staging(self.db, [empty])
        self.assertEqual(out["skipped"], 1)
        self.assertEqual(self._count("posts"), 0)


class TestMergeCatalogsContract(unittest.TestCase):
    """merge_catalogs.py must be able to read this staging shape."""

    def test_source_family_is_staging(self):
        db = Path(tempfile.mkdtemp()) / "5movierulz.db"
        mr.export_staging(db, [_post()])
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        import merge_catalogs
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        self.assertEqual(merge_catalogs._source_family(conn), "staging")
        post_row = conn.execute("SELECT * FROM posts").fetchone()
        collected = merge_catalogs._collect_staging_post(conn, post_row, "5movierulz")
        conn.close()
        self.assertEqual(collected["source_site"], "5movierulz")
        self.assertEqual(collected["canonical_key"], "the-paradise-2026")
        self.assertEqual(len(collected["releases"]), 5)
        self.assertEqual(collected["releases"][0]["quality"], "4K")


class TestSignalSafety(unittest.TestCase):
    def test_stop_flag_is_honoured_by_the_worker(self):
        mr.STOP_REQUESTED = True
        try:
            with mock.patch.object(mr, "_parse_page") as parse:
                totals = mr.crawl_pending(
                    db_path=Path(tempfile.mkdtemp()) / "x.db", workers=1, verbose=False)
        finally:
            mr.STOP_REQUESTED = False
        self.assertEqual(totals["pages"], 0)
        parse.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
