#!/usr/bin/env python3
"""
test_moviecok_import.py — offline unit tests for the moviecok staging importer.

No test opens a socket: every HTTP answer is a fixture, and the probe-off path
is asserted against mocks that raise if touched.
"""

from __future__ import annotations

import inspect
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import import_moviecok as mc  # noqa: E402

MOVIE_URL = ("https://moviecok.xyz/free-babbar-2022-hindi-punjabi-dual-audio-"
             "uncut-movie-hd-esub/")
SERIES_URL = ("https://moviecok.xyz/free-matargashti-s01-2026-hindi-completed-"
              "web-series-hevc-esub/")
SHORT = "https://10moviesz.mom/?id=f8512cf8"


def btn(quality: str, href: str = SHORT, icon: str = "⚡") -> str:
    return (f'<a href="{href}" class="mv-dl-btn" target="_blank">'
            f'<span class="mv-btn-icon">{icon}</span> '
            f'<span class="mv-btn-text">DOWNLOAD {quality}</span> '
            f'<span class="mv-btn-arrow">⬇</span></a>')


MOVIE_FIXTURE = f"""<!DOCTYPE html><html><head>
<title>Free Babbar (2022) (Hindi + Punjabi) Dual Audio UnCut Movie HD ESub - Bollyflix</title>
<meta name="description" content="Name: Free Babbar (2022) (Hindi + Punjabi) Dual Audio UnCut Movie HD ESub"/>
<meta property="og:title" content="Free Babbar (2022) (Hindi + Punjabi) Dual Audio UnCut Movie HD ESub - Bollyflix"/>
<meta property="og:site_name" content="HDHUB4U"/>
<meta property="og:image" content="https://moviecok.xyz/wp-content/uploads/2026/10/1000073857.png"/>
<meta name="keywords" content="Bollyflix, moviecok, free hd movies, filmycab"/>
</head><body>
<div class="mv-container">
 <div class="mv-top-title">Free Babbar (2022) (Hindi + Punjabi) Dual Audio UnCut Movie HD ESub</div>
 <div class="mv-poster"><img src="https://moviecok.xyz/wp-content/uploads/2026/10/1000073857.png" alt="poster"></div>
 <div class="mv-divider">----- MOVIE INFO -----</div>
 <div class="mv-info-name">Name: Free Babbar (2022) (Hindi + Punjabi) Dual Audio UnCut Movie HD ESub</div>
 <div class="mv-body-left">
  <div>
   <strong class="lbl-genre">Genre:</strong> <span class="val-genre">Action, Drama</span><br />
   <strong class="lbl-duration">Duration:</strong> <span class="val-duration">1h 57min</span><br />
   <strong class="lbl-release">Release Date:</strong> <span class="val-release">2022</span><br />
   <strong class="lbl-language">Language:</strong> <span class="val-language">Hindi + Punjabi</span><br />
   <strong class="lbl-starcast">Starcast:</strong> <span class="val-starcast">Amrit Maan, Yograj Singh</span><br />
   <strong class="lbl-size">Size:</strong> <span class="val-size">460Mb 730Mb 1.2Gb 2.7Gb 8.6Gb HD</span><br />
   <strong class="lbl-desc">Description:</strong> <span class="val-desc">Jorawar, once a mobster, wishes to have an easy going life with his brother.</span>
  </div>
 </div>
 <div class="mv-divider">----- SCREENSHOT -----</div>
 <div class="mv-screenshots"><img src="https://moviecok.xyz/wp-content/uploads/2026/10/screenshot_babbar-scaled-1.png" alt="Screenshot"></div>
 <div class="mv-download-box">
  <div class="mv-download-title">⚡ DOWNLOAD LINKS ⚡</div>
  {btn("480P")}
  {btn("720P HEVC")}
  {btn("720P")}
  {btn("1080P HEVC")}
  {btn("1080P")}
  {btn("1080P 4K")}
  <a href="https://10moviez.biz/" class="mv-main-site-btn"><span class="mv-btn-text">VISIT MAIN WEBSITE</span></a>
 </div>
 <div class="mv-related-header">⚡ RELATED MOVIES ⚡</div>
 <div class="mv-related-container">
  <a href="https://moviecok.xyz/free-related-secret-2026/" class="mv-related-item">
   <div class="mv-related-title">Related Secret (2026) Hindi Movie</div></a>
 </div>
</div>
<div class="ad"><a href="https://bit.ly/4nUa9x2">app</a></div>
</body></html>"""

SERIES_FIXTURE = """<!DOCTYPE html><html><head>
<title>Free Matargashti S01 (2026) Hindi Completed Web Series HEVC ESub - Bollyflix</title>
<meta name="description" content="Name: Free Matargashti S01 (2026) Hindi Completed Web Series HEVC ESub"/>
</head><body>
<div class="mv-container">
 <div class="mv-top-title">Free Matargashti S01 (2026) Hindi Completed Web Series HEVC ESub</div>
 <div class="mv-poster"><img src="https://moviecok.xyz/wp-content/uploads/2026/10/photo_matargashti.png"></div>
 <div class="mv-info-name">Name: Free Matargashti S01 (2026) Hindi Completed Web Series HEVC ESub</div>
 <div class="mv-body-left"><div>
  <strong class="lbl-genre">Genre:</strong> <span class="val-genre">Drama</span><br />
  <strong class="lbl-duration">Duration:</strong> <span class="val-duration">1h 48min</span><br />
  <strong class="lbl-release">Release Date:</strong> <span class="val-release">2026</span><br />
  <strong class="lbl-language">Language:</strong> <span class="val-language">Hindi</span><br />
  <strong class="lbl-starcast">Starcast:</strong> <span class="val-starcast">Rajesh Kumar</span><br />
  <strong class="lbl-size">Size:</strong> <span class="val-size">350Mb 670Mb 1.8Gb HEVC</span><br />
  <strong class="lbl-desc">Description:</strong> <span class="val-desc">Dhara's plan to explore her sexuality puts her at odds with her father.</span>
 </div></div>
 <div class="mv-screenshots"><img src="https://moviecok.xyz/wp-content/uploads/2026/10/screenshot_matargashti.png"></div>
 <div class="mv-download-box">
  <div class="mv-download-title">⚡ DOWNLOAD LINKS ⚡</div>
  <a href="https://10moviesz.mom/?id=699c88b4" class="mv-dl-btn"><span class="mv-btn-text">DOWNLOAD 480P</span></a>
  <a href="https://10moviesz.mom/?id=699c88b4" class="mv-dl-btn"><span class="mv-btn-text">DOWNLOAD 720P HEVC</span></a>
  <a href="https://10moviesz.mom/?id=699c88b4" class="mv-dl-btn"><span class="mv-btn-text">DOWNLOAD 1080P HEVC</span></a>
 </div>
 <div class="mv-related-header">⚡ RELATED MOVIES ⚡</div>
</div></body></html>"""

SUBS_DIV = """<div class="mv-subs">
 <a href="https://moviecok.xyz/wp-content/uploads/subs/Babbar.2022.English.srt">English</a>
 <a href="https://moviecok.xyz/wp-content/uploads/subs/Babbar.2022.Hindi.vtt">Hindi</a>
 <a href="https://moviecok.xyz/wp-content/uploads/subs/Babbar.2022.Urdu.ass">Urdu</a>
</div>"""
SUBTITLE_FIXTURE = MOVIE_FIXTURE.replace('<div class="mv-download-box">',
                                         SUBS_DIV + '\n <div class="mv-download-box">')
UNKNOWN_SUB_FIXTURE = MOVIE_FIXTURE.replace(
    '<div class="mv-download-box">',
    '<div><a href="https://moviecok.xyz/wp-content/uploads/subs/track.srt"></a></div>'
    '\n <div class="mv-download-box">')
ADULT_FIXTURE = MOVIE_FIXTURE.replace("Action, Drama", "Erotic, Romance")
BRANDED_FIXTURE = MOVIE_FIXTURE.replace(
    "Jorawar, once a mobster", "Bollyflix filmycab Jorawar, once a mobster")

HOMEPAGE_FIXTURE = """<html><head>
<title>bollyflix hollywood movies download free Bollywood bollyflex south movies</title>
</head><body><div class="bf-header-wrapper">Bollyflix Your Hub for Bollywood</div></body></html>"""

BRIDGE_PAGE = """<html><body>
<a href="https://hubcloud.ist/drive/abc123">1080P HubCloud</a>
<a href="https://pixeldrain.com/u/XYZ789">1080P PixelDrain</a>
<a href="https://drive.google.com/file/d/abc/view">480P GDrive</a>
<a href="https://cdn.example.com/babbar.720p.m3u8">720P Watch Online</a>
<a href="https://hubcloud.ist/drive/backup">Backup Server</a>
<a href="https://subs.example.com/Babbar.2022.English.srt">English</a>
</body></html>"""

CF_GATE = """<!DOCTYPE html><html><head><title>Just a moment...</title></head>
<body><div id="challenge-platform">Enable JavaScript and cookies to continue</div></body></html>"""


def fake_cf(url, referer=None, timeout=25):
    return 403, None, CF_GATE


def fake_dead(url, referer=None, timeout=25):
    return 404, None, "Not Found"


def fake_blocked(url, referer=None, timeout=25):
    return 403, None, "Forbidden"


def fake_bridge(url, referer=None, timeout=25):
    return 200, "https://10moviesz.mom/view/f8512cf8", BRIDGE_PAGE


def movie_post():
    return mc.parse_page(MOVIE_FIXTURE, MOVIE_URL)


class TestUrlNormalisation(unittest.TestCase):
    def test_entities_are_unescaped_before_quoting(self):
        got = mc.normalize_request_url(
            "https://moviecok.xyz/free-a b/?x=1&amp;y=2")
        self.assertEqual(got, "https://moviecok.xyz/free-a%20b/?x=1&y=2")

    def test_reserved_separators_and_existing_escapes_survive(self):
        got = mc.normalize_request_url(
            "https://moviecok.xyz/free-a%20b/?q=x&r=1#frag")
        self.assertEqual(got, "https://moviecok.xyz/free-a%20b/?q=x&r=1#frag")

    def test_unicode_is_percent_encoded(self):
        got = mc.normalize_request_url("https://moviecok.xyz/The Trap – Hindi")
        self.assertIn("%E2%80%93", got)
        self.assertNotIn(" ", got)

    def test_http_get_requests_the_quoted_url(self):
        resp = mock.Mock()
        resp.status = 200
        resp.geturl.return_value = "https://moviecok.xyz/free-a%20b/"
        resp.read.return_value = b"ok"
        with mock.patch.object(mc._OPENER, "open", return_value=resp) as opened:
            status, _final, body = mc.http_get("https://moviecok.xyz/free-a b/")
        self.assertEqual((status, body), (200, "ok"))
        self.assertEqual(opened.call_args[0][0], "https://moviecok.xyz/free-a%20b/")

    def test_http_get_once_quotes_url_and_referer(self):
        resp = mock.Mock()
        resp.status = 200
        resp.headers = {}
        resp.read.return_value = b"ok"
        with mock.patch.object(mc._NO_REDIRECT_OPENER, "open", return_value=resp) as opened:
            mc.http_get_once("https://10moviesz.mom/?id=a b",
                             referer="https://moviecok.xyz/free-a b/")
        request = opened.call_args[0][0]
        self.assertIn("a%20b", request.full_url)
        self.assertIn("a%20b", request.headers.get("Referer"))


class TestTitleCleaning(unittest.TestCase):
    def test_live_movie_heading_is_cleaned(self):
        got = mc.parse_title(
            "Free Babbar (2022) (Hindi + Punjabi) Dual Audio UnCut Movie HD ESub",
            "babbar-2022-hindi-punjabi-dual-audio-uncut-movie-hd-esub")
        self.assertEqual(got["clean_title"], "Babbar")
        self.assertEqual(got["year"], 2022)
        self.assertEqual(got["media_type"], "movie")
        self.assertEqual(got["languages"], ["Hindi", "Punjabi"])
        self.assertEqual(got["canonical_key"], "babbar_2022")

    def test_series_heading_keeps_its_name_and_reads_the_season(self):
        got = mc.parse_title(
            "Free Matargashti S01 (2026) Hindi Completed Web Series HEVC ESub",
            "matargashti-s01-2026-hindi-completed-web-series-hevc-esub")
        self.assertEqual(got["clean_title"], "Matargashti")
        self.assertEqual(got["season_number"], 1)
        self.assertEqual(got["media_type"], "series")
        self.assertEqual(got["canonical_key"], "matargashti_2026_s01")

    def test_one_free_prefix_is_stripped_so_a_film_named_free_survives(self):
        got = mc.parse_title("Free Free Guy (2021) Hindi Dubbed Movie",
                             "free-free-guy-2021-hindi-dubbed-movie")
        self.assertEqual(got["clean_title"], "Free Guy")
        self.assertEqual(got["canonical_key"], "free-guy_2021")

    def test_a_film_named_for_a_year_keeps_its_name(self):
        for title, year in (("Free 1922 (2017) English Movie", 2017),
                            ("Free 1917 (2019) English Movie", 2019),
                            ("Free 2018 (2023) Tamil Movie", 2023)):
            with self.subTest(title=title):
                got = mc.parse_title(title, title.lower().replace(" ", "_"))
                self.assertEqual(got["clean_title"], title.split(" (")[0].replace("Free ", ""))
                self.assertEqual(got["year"], year)

    def test_the_bracketed_year_outranks_the_name(self):
        got = mc.parse_title("Free 1922 (2017) English Movie", "")
        self.assertEqual((got["clean_title"], got["year"]), ("1922", 2017))

    def test_the_brand_suffix_is_not_part_of_the_name(self):
        got = mc.parse_title("Free Babbar (2022) Hindi Movie - Bollyflix", "")
        self.assertEqual(got["clean_title"], "Babbar")

    def test_an_alternate_title_in_brackets_is_kept(self):
        got = mc.parse_title("Free Raj Mahal 3 (Dhilluku Dhuddu) (2026) Movie", "x")
        self.assertIn("Dhilluku Dhuddu", got["clean_title"])

    def test_an_unclosed_bracket_does_not_hang_off_the_title(self):
        got = mc.parse_title(
            "Free The Return Of Jafar - Aladin 2 (1994 Hindi Dubbed Movie", "x")
        self.assertEqual(got["clean_title"], "The Return Of Jafar - Aladin 2")

    def test_a_descriptor_that_opens_the_title_is_part_of_the_name(self):
        self.assertEqual(mc.parse_title("Free Dual (2025) Hindi Movie", "")["clean_title"],
                         "Dual")
        self.assertEqual(
            mc.parse_title("Free Complete Unknown (2016) English Movie", "")["clean_title"],
            "Complete Unknown")

    def test_two_slug_variants_of_one_film_share_a_key(self):
        a = mc.build_canonical_key("Babbar", 2022, None, None,
                                   "Babbar_2022_hindi_dubbed_movie")
        b = mc.build_canonical_key("Babbar", 2022, None, None,
                                   "Babbar_2022_punjabi_movie")
        self.assertEqual(a, b)

    def test_numeric_titles_survive_the_right_trim(self):
        self.assertEqual(mc._slug_title_base("Jailer_2_(2026)_hindi_dubbed_movie"),
                         "jailer-2")
        self.assertEqual(mc._slug_title_base("3_idiots_(2009)_movie"), "3-idiots")
        self.assertEqual(mc._slug_title_base("free-418-2026-south-movie-hindi-hdtc"), "418")

    def test_a_show_keeps_the_word_show_when_it_is_its_name(self):
        got = mc.parse_title(
            "Free The Great Indian Kapil Show Season 5 Hindi TV Show S05E01 "
            "26 September 2026 Added Web-DL",
            "the-great-indian-kapil-show-season-5-hindi-tv-show-s05e01-"
            "26-september-2026-added-web-dl")
        self.assertEqual(got["clean_title"], "The Great Indian Kapil Show")
        self.assertEqual((got["season_number"], got["episode_number"]), (5, 1))
        self.assertEqual(got["year"], 2026)

    def test_a_reality_show_episode_reads_season_and_episode(self):
        got = mc.parse_title(
            "Free Bigg Boss Season 20 Hindi Reality Show Web-DL Episode 22 "
            "Added Colors TV",
            "bigg-boss-season-20-hindi-reality-show-web-dl-episode-22-added-colors-tv")
        self.assertEqual(got["clean_title"], "Bigg Boss")
        self.assertEqual((got["season_number"], got["episode_number"]), (20, 22))

    def test_a_season_range_is_one_season(self):
        got = mc.parse_title(
            "Free The Legend of Hanuman S1-7 (2026) Hindi Completed Web Series HD ESub",
            "the-legend-of-hanuman-s1-7-2026-hindi-completed-web-series-hd-esub")
        self.assertEqual(got["clean_title"], "The Legend of Hanuman")
        self.assertEqual(got["season_number"], 1)

    def test_platform_and_episode_packaging_is_removed(self):
        got = mc.parse_title(
            "Free The Trap (2026) Season 1 All Episodes [Hindi ORG. + Multi Audio] "
            "Complete Netflix Original Web Series",
            "the-trap-2026-season-1-all-episodes-hindi-org-multi-audio-"
            "complete-netflix-original-web-series")
        self.assertEqual(got["clean_title"], "The Trap")
        self.assertEqual(got["season_number"], 1)
        self.assertEqual(got["media_type"], "series")


class TestProvenanceScrub(unittest.TestCase):
    def test_site_and_sister_brands_are_removed(self):
        for token in ("Bollyflix", "BOLLYFLEX 2026", "Moviecok", "BollyShares",
                      "HDHUB4U", "10moviesz", "10moviez.biz", "filmycab", "filmyfly"):
            with self.subTest(token=token):
                out = mc.scrub_brand(token).lower()
                self.assertNotIn(token.split()[0].lower().split(".")[0], out)

    def test_a_real_title_is_not_eaten_by_the_scrubber(self):
        self.assertEqual(mc.scrub_brand("Bollywood Dreamz"), "Bollywood Dreamz")
        self.assertEqual(mc.scrub_brand("The Free Guy"), "The Free Guy")

    def test_title_and_synopsis_are_scrubbed_in_the_stored_post(self):
        post = mc.parse_page(BRANDED_FIXTURE, MOVIE_URL)
        self.assertNotIn("bollyflix", (post["title"] or "").lower())
        self.assertNotIn("filmycab", (post["synopsis"] or "").lower())


class TestAdultFlagging(unittest.TestCase):
    def test_shelf_labels_flag_adult_content(self):
        self.assertTrue(mc.is_adult_content("Some Film", "Erotic, Romance"))
        self.assertTrue(mc.is_adult_content("Some Film", "Brazzers Originals"))
        self.assertTrue(mc.is_adult_content("Title", "", "", "18+"))
        self.assertTrue(mc.is_adult_content("Charmsukh S03", "Drama"))

    def test_mainstream_labels_are_not_flagged(self):
        self.assertFalse(mc.is_adult_content("Gods Own Country (2014) Movie",
                                             "Malayalam Movies", "Drama"))
        self.assertFalse(mc.is_adult_content("Babbar (2022)", "Action, Drama"))

    def test_ambiguous_words_in_prose_do_not_flag(self):
        blurb = ("A bold, sensual story of lust and temptation with adult themes "
                 "handled delicately.")
        self.assertFalse(mc.is_adult_content("Dil Padosi S01", "Drama, Romance",
                                             prose=(blurb,)))
        self.assertTrue(mc.is_adult_content("Dil Padosi S01", "Adult, Drama"))

    def test_an_explicit_prose_marker_does_flag(self):
        self.assertTrue(mc.is_adult_content(
            "Some Film", "Drama", prose=("An OnlyFans performer stars.",)))

    def test_the_live_series_synopsis_is_not_adult(self):
        post = mc.parse_page(SERIES_FIXTURE, SERIES_URL)
        self.assertEqual(post["is_18_plus"], 0)


class TestQualityAndSize(unittest.TestCase):
    def test_the_four_catalog_rungs_are_normalised(self):
        self.assertEqual(mc.normalize_quality("DOWNLOAD 1080P 4K"), "4k")
        self.assertEqual(mc.normalize_quality("2160p"), "4k")
        self.assertEqual(mc.normalize_quality("UHD"), "4k")
        self.assertEqual(mc.normalize_quality("720P HEVC"), "720p")
        self.assertIsNone(mc.normalize_quality("HD"))

    def test_codecs_are_read_from_the_button(self):
        self.assertEqual(mc.normalize_codec("720P HEVC"), "HEVC")
        self.assertEqual(mc.normalize_codec("1080P x265"), "X265")
        self.assertIsNone(mc.normalize_codec("480P"))

    def test_site_sizes_are_binary(self):
        self.assertEqual(mc.parse_size_to_bytes("460Mb"), int(460 * 1024 ** 2))
        self.assertEqual(mc.parse_size_to_bytes("1.2Gb"), int(1.2 * 1024 ** 3))
        self.assertEqual(mc.parse_size_to_bytes("329.113 MB"), int(329.113 * 1024 ** 2))
        self.assertIsNone(mc.parse_size_to_bytes("0.000 MB"))
        self.assertIsNone(mc.parse_size_to_bytes("1.499 KB"))

    def test_a_size_below_a_megabyte_is_a_placeholder(self):
        for text in ("-1.000 B", "753.000 B", "0 KB", None, "n/a"):
            with self.subTest(text=text):
                self.assertIsNone(mc.parse_size_to_bytes(text))


class TestDownloadButtons(unittest.TestCase):
    def test_every_quality_button_becomes_a_print(self):
        post = movie_post()
        self.assertEqual([r["label"] for r in post["releases"]],
                         ["480P", "720P HEVC", "720P", "1080P HEVC", "1080P",
                          "1080P 4K"])
        self.assertEqual([r["quality"] for r in post["releases"]],
                         ["480p", "720p", "720p", "1080p", "1080p", "4k"])
        self.assertEqual([r["codec"] for r in post["releases"]],
                         [None, "HEVC", None, "HEVC", None, None])

    def test_the_shared_short_link_is_kept_on_every_print(self):
        post = movie_post()
        self.assertEqual(len(post["releases"]), 6)
        for release in post["releases"]:
            self.assertEqual(len(release["sources"]), 1)
            self.assertEqual(release["sources"][0]["source_url"], SHORT)
            self.assertEqual(release["sources"][0]["service"], "bridge")
            self.assertEqual(release["sources"][0]["status"], "unknown")
            self.assertEqual(release["sources"][0]["is_temporary"], 0)

    def test_buttons_are_grouped_by_print_not_by_url(self):
        fixture = MOVIE_FIXTURE.replace(
            btn("480P"), btn("480P") + btn("480P", "https://hubcloud.ist/drive/x"))
        post = mc.parse_page(fixture, MOVIE_URL)
        first = post["releases"][0]
        self.assertEqual(first["quality"], "480p")
        self.assertEqual(len(first["sources"]), 2)
        self.assertEqual({s["service"] for s in first["sources"]},
                         {"bridge", "hubcloud"})
        self.assertEqual(len(post["releases"]), 6)

    def test_an_ambiguous_size_run_is_not_invented(self):
        post = movie_post()
        self.assertTrue(all(r["size_bytes"] is None for r in post["releases"]))
        self.assertEqual(len(post["raw_meta"]["size_tokens"]), 5)

    def test_a_positional_size_run_is_applied(self):
        post = mc.parse_page(SERIES_FIXTURE, SERIES_URL)
        self.assertEqual([r["size_bytes"] for r in post["releases"]],
                         [int(350 * 1024 ** 2), int(670 * 1024 ** 2),
                          int(1.8 * 1024 ** 3)])


class TestSubtitles(unittest.TestCase):
    def setUp(self):
        self.post = mc.parse_page(SUBTITLE_FIXTURE, MOVIE_URL)

    def test_each_track_is_its_own_subtitle_source(self):
        subs = [s for r in self.post["releases"] for s in r["sources"]
                if s["playback_type"] == "subtitle"]
        self.assertEqual(len(subs), 3)
        self.assertEqual({s["service"] for s in subs}, {"subtitle"})

    def test_every_language_is_named_and_kept(self):
        subs = [s for r in self.post["releases"] for s in r["sources"]
                if s["playback_type"] == "subtitle"]
        self.assertEqual(sorted(s["source_name"] for s in subs),
                         ["English subtitles", "Hindi subtitles", "Urdu subtitles"])
        self.assertEqual({s["source_url"].rsplit(".", 1)[-1] for s in subs},
                         {"srt", "vtt", "ass"})

    def test_the_track_list_is_echoed_in_raw_meta(self):
        tracks = self.post["raw_meta"]["subtitles"]
        self.assertEqual(len(tracks), 3)
        self.assertEqual({t["language"] for t in tracks},
                         {"English", "Hindi", "Urdu"})

    def test_an_unnameable_language_is_kept_as_unknown(self):
        post = mc.parse_page(UNKNOWN_SUB_FIXTURE, MOVIE_URL)
        subs = [s for r in post["releases"] for s in r["sources"]
                if s["playback_type"] == "subtitle"]
        self.assertEqual(len(subs), 1)
        self.assertEqual(subs[0]["source_name"], "Unknown subtitles")


class TestParsePage(unittest.TestCase):
    def test_the_live_movie_page_yields_a_staging_shaped_post(self):
        post = movie_post()
        self.assertEqual(post["clean_title"], "Babbar")
        self.assertEqual(post["year"], 2022)
        self.assertEqual(post["content_type"], "movie")
        self.assertEqual(post["source_site"], "moviecok")
        self.assertEqual(post["is_18_plus"], 0)
        self.assertEqual(post["genres"], "Action, Drama")
        self.assertEqual(post["languages"], "Hindi, Punjabi")
        self.assertEqual(post["duration"], "1h 57min")
        self.assertEqual(post["cast_names"], "Amrit Maan, Yograj Singh")
        self.assertIn("Jorawar", post["synopsis"])
        self.assertTrue(post["poster_url"].endswith("1000073857.png"))
        self.assertEqual(len(post["releases"]), 6)

    def test_screenshots_become_backdrops(self):
        post = movie_post()
        self.assertEqual(len(post["backdrop_urls"]), 1)
        self.assertIn("screenshot_babbar", post["backdrop_urls"][0])

    def test_the_series_page_is_typed_and_seasoned(self):
        post = mc.parse_page(SERIES_FIXTURE, SERIES_URL)
        self.assertEqual(post["clean_title"], "Matargashti")
        self.assertEqual(post["content_type"], "series")
        self.assertEqual(post["season_number"], 1)
        self.assertEqual(post["canonical_key"], "matargashti_2026_s01")
        self.assertEqual(len(post["releases"]), 3)

    def test_placeholder_metadata_is_stored_as_null(self):
        fixture = (MOVIE_FIXTURE
                   .replace('<span class="val-starcast">Amrit Maan, Yograj Singh</span>',
                            '<span class="val-starcast">n/a</span>')
                   .replace('<span class="val-duration">1h 57min</span>',
                            '<span class="val-duration">n/a</span>')
                   .replace('<span class="val-desc">Jorawar, once a mobster, wishes to '
                            'have an easy going life with his brother.</span>',
                            '<span class="val-desc">n/a</span>'))
        post = mc.parse_page(fixture, MOVIE_URL)
        self.assertIsNone(post["synopsis"])
        self.assertIsNone(post["cast_names"])
        self.assertIsNone(post["duration"])

    def test_the_sites_own_release_date_outranks_the_title_year(self):
        fixture = MOVIE_FIXTURE.replace(
            '<span class="val-release">2022</span>',
            '<span class="val-release">19 August,2005</span>')
        post = mc.parse_page(fixture, MOVIE_URL)
        self.assertEqual(post["year"], 2005)

    def test_related_posts_are_not_this_posts_metadata(self):
        post = movie_post()
        blob = json.dumps(post["raw_meta"], ensure_ascii=False)
        self.assertNotIn("Related Secret", blob)

    def test_the_front_page_is_not_a_catalog_entry(self):
        self.assertIsNone(mc.parse_page(HOMEPAGE_FIXTURE, "https://moviecok.xyz/"))
        self.assertEqual(mc._parse_page(HOMEPAGE_FIXTURE,
                                        "https://moviecok.xyz/")[1], "not-a-post")

    def test_shelves_and_static_pages_are_not_posts(self):
        for url in ("https://moviecok.xyz/category/bollywood/",
                    "https://moviecok.xyz/page-sitemap.xml",
                    "https://moviecok.xyz/contact/"):
            with self.subTest(url=url):
                self.assertIsNone(mc.parse_page(MOVIE_FIXTURE, url))

    def test_a_removed_post_that_answers_the_front_page_is_parked(self):
        with mock.patch.object(mc, "http_get",
                               return_value=(200, "https://moviecok.xyz/",
                                             HOMEPAGE_FIXTURE)):
            self.assertEqual(mc._parse_page(MOVIE_URL)[1], "removed")

    def test_a_markup_change_is_retried_not_parked(self):
        body = '<html><head><title>Sign in</title></head><body>Login</body></html>'
        self.assertEqual(mc._parse_page(body, MOVIE_URL)[1], "parse-error")

    def test_a_transport_error_is_an_http_error(self):
        with mock.patch.object(mc, "http_get", return_value=(500, "", "")):
            self.assertEqual(mc._parse_page(MOVIE_URL)[1], "http-error")

    def test_the_url_form_fetches_through_http_get(self):
        with mock.patch.object(mc, "http_get", return_value=(200, MOVIE_URL, MOVIE_FIXTURE)):
            post = mc.parse_page(MOVIE_URL)
        self.assertEqual(post["clean_title"], "Babbar")


class TestResolveLinks(unittest.TestCase):
    def test_probe_off_opens_no_socket_and_leaves_rows_untouched(self):
        post = movie_post()
        with mock.patch.object(mc, "http_get", side_effect=AssertionError("network")), \
             mock.patch.object(mc, "http_get_once", side_effect=AssertionError("network")):
            out = mc.resolve_links(post, probe=False)
        self.assertEqual([s["status"] for r in out["releases"] for s in r["sources"]],
                         ["unknown"] * 6)

    def test_cloudflare_challenge_is_recorded_as_js_required(self):
        post = movie_post()
        with mock.patch.object(mc, "http_get_once", side_effect=fake_cf):
            post = mc.resolve_links(post, probe=True)
        statuses = [s["status"] for r in post["releases"] for s in r["sources"]]
        self.assertEqual(statuses, ["js_required"] * 6)

    def test_one_shared_bridge_is_probed_once(self):
        post = movie_post()
        with mock.patch.object(mc, "http_get_once", side_effect=fake_cf) as probed:
            mc.resolve_links(post, probe=True)
        self.assertEqual(probed.call_count, 1)

    def test_a_dead_bridge_is_kept_as_dead(self):
        post = movie_post()
        with mock.patch.object(mc, "http_get_once", side_effect=fake_dead):
            post = mc.resolve_links(post, probe=True)
        self.assertEqual(len(post["releases"]), 6)
        self.assertEqual({s["status"] for r in post["releases"] for s in r["sources"]},
                         {"dead"})

    def test_a_non_challenge_403_is_blocked(self):
        post = movie_post()
        with mock.patch.object(mc, "http_get_once", side_effect=fake_blocked):
            post = mc.resolve_links(post, probe=True)
        self.assertEqual({s["status"] for r in post["releases"] for s in r["sources"]},
                         {"blocked"})

    def test_a_reachable_bridge_supplies_tiered_mirrors(self):
        post = movie_post()
        with mock.patch.object(mc, "http_get_once", side_effect=fake_bridge):
            post = mc.resolve_links(post, probe=True)
        by_quality = {}
        for release in post["releases"]:
            by_quality.setdefault(release["quality"], []).extend(
                s["service"] for s in release["sources"])
        self.assertIn("gdrive", by_quality["480p"])
        self.assertIn("hubcloud", by_quality["1080p"])
        self.assertIn("pixeldrain", by_quality["1080p"])
        self.assertIn("cdn.example.com", by_quality["720p"])

    def test_an_untiered_mirror_is_audited_but_not_claimed_for_a_rung(self):
        post = movie_post()
        with mock.patch.object(mc, "http_get_once", side_effect=fake_bridge):
            post = mc.resolve_links(post, probe=True)
        backup = post["raw_meta"]["bridge_mirrors"]
        self.assertTrue(any(m["source_url"].endswith("/backup") for m in backup))
        for release in post["releases"]:
            self.assertFalse(any((s.get("source_url") or "").endswith("/backup")
                                 for s in release["sources"]))

    def test_a_bridge_page_subtitle_becomes_a_track(self):
        post = movie_post()
        with mock.patch.object(mc, "http_get_once", side_effect=fake_bridge):
            post = mc.resolve_links(post, probe=True)
        subs = [s for r in post["releases"] for s in r["sources"]
                if s["playback_type"] == "subtitle"]
        self.assertEqual(len(subs), 1)
        self.assertEqual(subs[0]["source_name"], "English subtitles")

    def test_a_200_bridge_without_mirrors_keeps_the_bridge_as_active(self):
        post = movie_post()
        with mock.patch.object(mc, "http_get_once",
                               return_value=(200, SHORT, "<html>Nothing here</html>")):
            post = mc.resolve_links(post, probe=True)
        self.assertEqual({s["status"] for r in post["releases"] for s in r["sources"]},
                         {"active"})

    def test_a_redirect_chain_is_followed_to_the_bridge_page(self):
        def chain(url, referer=None, timeout=25):
            if "id=start" in url:
                return 302, "https://10moviesz.mom/next", ""
            return 200, "https://10moviesz.mom/next", BRIDGE_PAGE

        with mock.patch.object(mc, "http_get_once", side_effect=chain):
            outcome, final, body = mc._walk_bridge(
                "https://10moviesz.mom/?id=start", None)
        self.assertEqual(outcome, "ok")
        self.assertTrue(final.endswith("/next"))
        self.assertIn("hubcloud", body)


class TestStagingDatabase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = Path(self.tmp) / "moviecok.db"
        self.post = movie_post()

    def test_writes_only_the_isolated_staging_file(self):
        out = mc.export_staging(self.db, [self.post])
        self.assertEqual(out["posts_written"], 1)
        self.assertEqual(out["releases_written"], 6)
        self.assertEqual(out["sources_written"], 6)
        self.assertTrue(self.db.exists())

    def test_recrawl_is_idempotent(self):
        mc.export_staging(self.db, [self.post])
        mc.export_staging(self.db, [self.post])
        conn = sqlite3.connect(self.db)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0], 1)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM releases").fetchone()[0], 6)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0], 6)
        conn.close()

    def test_two_pages_of_one_title_keep_their_own_prints(self):
        first = dict(self.post, url=MOVIE_URL)
        second = dict(self.post, url=MOVIE_URL.replace("babbar", "babbar-pack"))
        mc.export_staging(self.db, [first])
        mc.export_staging(self.db, [second])
        conn = sqlite3.connect(self.db)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM releases").fetchone()[0], 12)
        self.assertEqual(conn.execute(
            "SELECT COUNT(DISTINCT origin_url) FROM releases").fetchone()[0], 2)
        conn.close()

    def test_source_columns_are_the_ones_the_catalog_reads(self):
        mc.export_staging(self.db, [self.post])
        conn = sqlite3.connect(self.db)
        cols = {c[1] for c in conn.execute("PRAGMA table_info(sources)")}
        conn.close()
        for needed in ("source_name", "service", "resource_id", "source_url",
                       "final_url", "playback_type", "is_temporary", "status"):
            self.assertIn(needed, cols)

    def test_no_provenance_token_reaches_a_display_column(self):
        post = mc.parse_page(BRANDED_FIXTURE, MOVIE_URL)
        mc.export_staging(self.db, [post])
        conn = sqlite3.connect(self.db)
        row = conn.execute(
            "SELECT title, clean_title, synopsis, genres FROM posts").fetchone()
        conn.close()
        joined = " ".join(str(v) for v in row).lower()
        for needle in ("bollyflix", "moviecok", "hdhub4u", "10moviesz", "10moviez",
                       "filmycab", "filmyfly", "bollyshares"):
            self.assertNotIn(needle, joined)

    def test_dead_links_are_retained_with_their_status(self):
        with mock.patch.object(mc, "http_get_once", side_effect=fake_dead):
            post = mc.resolve_links(self.post, probe=True)
        mc.export_staging(self.db, [post])
        conn = sqlite3.connect(self.db)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0], 6)
        self.assertEqual(conn.execute(
            "SELECT COUNT(*) FROM sources WHERE status = 'dead'").fetchone()[0], 6)
        conn.close()

    def test_subtitle_rows_are_persisted(self):
        post = mc.parse_page(SUBTITLE_FIXTURE, MOVIE_URL)
        out = mc.export_staging(self.db, [post])
        self.assertEqual(out["releases_written"], 6)
        self.assertEqual(out["sources_written"], 9)
        st = mc.get_stats(self.db)
        self.assertEqual(st["subtitles"], 3)

    def test_an_adult_row_is_stored_and_flagged(self):
        post = mc.parse_page(ADULT_FIXTURE, MOVIE_URL)
        self.assertEqual(post["is_18_plus"], 1)
        mc.export_staging(self.db, [post])
        self.assertEqual(mc.get_stats(self.db)["adult_flagged"], 1)

    def test_stats_and_status_counts(self):
        mc.export_staging(self.db, [self.post])
        st = mc.get_stats(self.db)
        self.assertEqual(st["posts"], 1)
        self.assertEqual(st["releases"], 6)
        self.assertEqual(st["sources"], 6)
        self.assertEqual(st["adult_flagged"], 0)
        self.assertEqual(st["source_status"], {"unknown": 6})
        self.assertEqual(st["services"], {"bridge": 6})

    def test_schema_carries_the_four_staging_tables(self):
        mc.export_staging(self.db, [self.post])
        conn = sqlite3.connect(self.db)
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        conn.close()
        self.assertTrue({"sitemap_cache", "posts", "releases", "sources"} <= tables)


class TestMergeCatalogsContract(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = Path(self.tmp) / "moviecok.db"
        mc.export_staging(self.db, [movie_post()])

    def test_source_family_is_staging(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        import merge_catalogs
        conn = sqlite3.connect(self.db)
        conn.row_factory = sqlite3.Row
        self.assertEqual(merge_catalogs._source_family(conn), "staging")
        conn.close()

    def test_collected_post_carries_the_site_and_its_prints(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        import merge_catalogs
        conn = sqlite3.connect(self.db)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM posts").fetchone()
        collected = merge_catalogs._collect_staging_post(conn, row, "moviecok")
        conn.close()
        self.assertEqual(collected["source_site"], "moviecok")
        self.assertEqual(collected["canonical_key"], "babbar_2022")
        self.assertEqual(collected["content_type"], "movie")
        self.assertEqual(len(collected["releases"]), 6)
        self.assertEqual(collected["releases"][0]["quality"], "480p")
        self.assertEqual(collected["releases"][0]["sources"][0]["service"], "bridge")


class TestSyncCatalog(unittest.TestCase):
    INDEX = ('<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/'
             'schemas/sitemap/0.9">'
             '<sitemap><loc>https://moviecok.xyz/post-sitemap1.xml</loc></sitemap>'
             '<sitemap><loc>https://moviecok.xyz/post-sitemap2.xml</loc></sitemap>'
             '<sitemap><loc>https://moviecok.xyz/page-sitemap.xml</loc></sitemap>'
             '</sitemapindex>')
    URLSET = ('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
              '<url><loc>https://moviecok.xyz/free-babbar-2022-hindi-punjabi-dual-'
              'audio-uncut-movie-hd-esub/</loc></url>'
              '<url><loc>https://moviecok.xyz/free-matargashti-s01-2026-hindi-'
              'completed-web-series-hevc-esub/</loc></url>'
              '<url><loc>https://moviecok.xyz/category/bollywood/</loc></url>'
              '</urlset>')

    def test_index_is_followed_and_shelves_are_skipped(self):
        tmp = Path(tempfile.mkdtemp()) / "moviecok.db"

        def get(url, timeout=30, retries=3):
            if url.endswith("/sitemap_index.xml"):
                return 200, url, self.INDEX
            if url.endswith("post-sitemap1.xml"):
                return 200, url, self.URLSET
            return 404, url, ""

        with mock.patch.object(mc, "http_get", side_effect=get) as called:
            added = mc.sync_catalog(db_path=tmp, verbose=False)
        self.assertEqual(added, 2)
        conn = sqlite3.connect(tmp)
        locs = [r[0] for r in conn.execute("SELECT loc FROM sitemap_cache")]
        conn.close()
        self.assertEqual(len(locs), 2)
        self.assertTrue(all("/free-" in loc for loc in locs))
        fetched = [c.args[0] for c in called.call_args_list]
        self.assertFalse(any("page-sitemap" in u for u in fetched))

    def test_the_limit_stops_before_fetching_more_child_sitemaps(self):
        tmp = Path(tempfile.mkdtemp()) / "moviecok.db"

        def get(url, timeout=30, retries=3):
            if url.endswith("/sitemap_index.xml"):
                return 200, url, self.INDEX
            if url.endswith("post-sitemap1.xml"):
                return 200, url, self.URLSET
            return 404, url, ""

        with mock.patch.object(mc, "http_get", side_effect=get) as called:
            added = mc.sync_catalog(limit=1, db_path=tmp, verbose=False)
        self.assertEqual(added, 1)
        fetched = [c.args[0] for c in called.call_args_list]
        self.assertFalse(any("post-sitemap2" in u for u in fetched))

    def test_a_missing_index_falls_back_to_the_post_sitemap(self):
        tmp = Path(tempfile.mkdtemp()) / "moviecok.db"

        def get(url, timeout=30, retries=3):
            if url.endswith("/sitemap_index.xml"):
                return 404, url, ""
            return 200, url, self.URLSET

        with mock.patch.object(mc, "http_get", side_effect=get):
            self.assertEqual(mc.sync_catalog(db_path=tmp, verbose=False), 2)

    def test_a_missing_child_sitemap_does_not_abort_the_run(self):
        tmp = Path(tempfile.mkdtemp()) / "moviecok.db"

        def get(url, timeout=30, retries=3):
            if url.endswith("/sitemap_index.xml"):
                return 200, url, self.INDEX
            return 404, url, ""

        with mock.patch.object(mc, "http_get", side_effect=get):
            self.assertEqual(mc.sync_catalog(db_path=tmp, verbose=False), 0)

    def test_resync_does_not_reset_indexed_pages(self):
        tmp = Path(tempfile.mkdtemp()) / "moviecok.db"

        def get(url, timeout=30, retries=3):
            if url.endswith("/sitemap_index.xml"):
                return 200, url, self.INDEX
            if url.endswith("post-sitemap1.xml"):
                return 200, url, self.URLSET
            return 404, url, ""

        with mock.patch.object(mc, "http_get", side_effect=get):
            mc.sync_catalog(db_path=tmp, verbose=False)
        conn = sqlite3.connect(tmp)
        conn.execute("UPDATE sitemap_cache SET scraped = 1")
        conn.commit()
        conn.close()
        with mock.patch.object(mc, "http_get", side_effect=get):
            again = mc.sync_catalog(db_path=tmp, verbose=False)
        self.assertEqual(again, 0)
        conn = sqlite3.connect(tmp)
        self.assertEqual(conn.execute(
            "SELECT COUNT(*) FROM sitemap_cache WHERE scraped = 1").fetchone()[0], 2)
        conn.close()


class TestCrawlQueue(unittest.TestCase):
    def _db_with(self, locs):
        tmp = Path(tempfile.mkdtemp()) / "moviecok.db"
        conn = sqlite3.connect(tmp)
        mc.ensure_schema(conn)
        for loc in locs:
            conn.execute("INSERT INTO sitemap_cache (loc, slug, scraped) VALUES (?, ?, 0)",
                         (loc, loc.strip("/").split("/")[-1]))
        conn.commit()
        conn.close()
        return tmp

    def _state(self, db, loc):
        conn = sqlite3.connect(db)
        row = conn.execute(
            "SELECT scraped, error_count FROM sitemap_cache WHERE loc = ?",
            (loc,)).fetchone()
        conn.close()
        return row

    def test_a_page_the_site_removed_is_parked_on_the_first_sighting(self):
        db = self._db_with([MOVIE_URL])
        with mock.patch.object(mc, "http_get",
                               return_value=(200, "https://moviecok.xyz/",
                                             HOMEPAGE_FIXTURE)):
            totals = mc.crawl_pending(db_path=db, workers=1, delay=0, verbose=False)
        self.assertEqual(totals["not_indexable"], 1)
        self.assertEqual(self._state(db, MOVIE_URL), (-1, 1))

    def test_a_markup_change_is_retried_rather_than_parked(self):
        db = self._db_with([MOVIE_URL])
        body = '<html><head><title>Sign in</title></head><body>Login</body></html>'
        with mock.patch.object(mc, "http_get", return_value=(200, MOVIE_URL, body)):
            mc.crawl_pending(db_path=db, workers=1, delay=0, verbose=False)
        self.assertEqual(self._state(db, MOVIE_URL), (0, 1))

    def test_stop_flag_is_honoured_by_the_worker(self):
        mc.STOP_REQUESTED = True
        try:
            with mock.patch.object(mc, "_parse_page") as parse:
                totals = mc.crawl_pending(
                    db_path=Path(tempfile.mkdtemp()) / "x.db", workers=1,
                    verbose=False)
        finally:
            mc.STOP_REQUESTED = False
        self.assertEqual(totals["pages"], 0)
        parse.assert_not_called()


class TestPublicContract(unittest.TestCase):
    def test_signatures_match_the_documented_contract(self):
        self.assertEqual(list(inspect.signature(mc.sync_catalog).parameters),
                         ["limit", "db_path", "verbose"])
        self.assertEqual(list(inspect.signature(mc.parse_page).parameters),
                         ["html_or_url", "url"])
        self.assertEqual(list(inspect.signature(mc.resolve_links).parameters),
                         ["post_data", "probe"])
        self.assertEqual(list(inspect.signature(mc.export_staging).parameters),
                         ["db_path", "posts"])
        self.assertEqual(list(inspect.signature(mc.get_stats).parameters),
                         ["db_path"])

    def test_the_default_database_is_the_isolated_moviecok_file(self):
        self.assertEqual(mc.DEFAULT_DB_PATH,
                         Path("/home/ubuntu/radd-stream-data/moviecok.db"))

    def test_discovery_never_uses_the_slow_root_sitemap(self):
        self.assertTrue(mc.SITEMAP_INDEX_URL.endswith("/sitemap_index.xml"))
        self.assertNotEqual(mc.SITEMAP_INDEX_URL, "https://moviecok.xyz/sitemap.xml")


if __name__ == "__main__":
    unittest.main(verbosity=2)
