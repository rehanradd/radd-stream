#!/usr/bin/env python3
"""
test_pagalmovies_import.py — offline unit tests for the pagalmovies staging importer.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import import_pagalmovies as pm  # noqa: E402

FIXTURE = """<!DOCTYPE html><html><head>
<title>Eyes 2026 Atrangii Hot Short Film Download Pagalmovies</title>
<meta property="og:title" content="Eyes (2026) Atrangii Full Hot Short Film">
<meta property="og:description" content="n/a">
<meta name="keywords" content="Pagalmovies, pagalmovies 2026, free hd movies download, filmyhit">
</head><body>
<div class="Fun"><b>Movie Name:</b> <font>Eyes (2026) Atrangii Full Hot Short Film</font></div>
<div class="Fun"><b>Category:</b> <i><a href="https://www.pagalmovies.fit/movielist/24/Hot_short_films/default/1.html">Hot Short Films</a></i></div>
<div class="Fun"><b>Starcast:</b> <a href="https://www.pagalmovies.fit/starcast/n/a/1.html"><i>n/a</i></a></div>
<div class="Fun"><b>Description:</b> <i>n/a</i></div>
<div class="Fun"><b>Genre:</b> <a href="https://www.pagalmovies.fit/genre/Erotic/1.html"><i>Erotic</i></a>, <a href="https://www.pagalmovies.fit/genre/Romance/1.html"><i>Romance</i></a></div>
<div class="Fun"><b>Release Date:</b> <i>2026</i></div>
<div class="Fun"><b>Duration:</b> <i>n/a</i></div>
<div class="Fun"><b>Updated Webseries:</b> <a href="/movie/1/Hunkkaar_2026.html">Hunkkaar: The Roar (2026) S01 Jiohotstar Hindi Web Series</a> | <a href="/movie/2/Waiting_Hai_2026.html">Waiting Hai (2026) S01 Amazon Prime Hindi Web Series</a></div>
<h1 class="subox" align="left">Eyes (2026) Atrangii Full Hot Short Film</h1>
<p class="showimage"><img class="absmiddle" src="https://www.pagalmovies.fit/files/images/Eyes_(2026)_Atrangii_Full_Hot_Short_Film.jpg" height="260" width="220"/></p>
<h2 class="subox">Download Eyes (2026) Atrangii Full Hot Short Film</h2>
<div class="list">
 <div class="L"><a href="https://bit.ly/4nUa9x2"><b>Download/Watch in Android APP</b></a></div>
 <div class="pm-q-head pm-q-720"><span class="pm-q-badge">720p</span><span class="pm-q-count">1 file</span></div>
 <div class="M1"><a class="fileName" href="https://www.pagalmovies.fit/file/21801/Eyes_2026_atrangii_full_hot_short_film_720p_hdrip.mp4.html"><div>Eyes 2026 Atrangii Full Hot Short Film 720p HDRip.mp4<br/><span>File Size: 329.113 MB</span></div></a></div>
 <div class="pm-q-head pm-q-1080"><span class="pm-q-badge">1080p</span><span class="pm-q-count">1 file</span></div>
 <div class="M1"><a class="fileName" href="https://www.pagalmovies.fit/file/21800/Eyes_2026_atrangii_full_hot_short_film_1080p_hdrip.mp4.html"><div>Eyes 2026 Atrangii Full Hot Short Film 1080p HDRip.mp4<br/><span>File Size: 1.21 GB</span></div></a></div>
</div>
<div class="des">Eyes,Gods Own Country coolmoviez,Download Pagalmovies 2026</div>
<div class="ad"><a href="https://cvt-s2.agl002.online/o/s/636b.js">ad</a>
 <a href="https://allmovielandapp.org/allmovieland.apk">apk</a>
 <a href="https://www.pagalmovies.com.co">mirror</a></div>
<div class="navi"><a href="https://www.pagalmovies.fit/movie/29565/Jailer_2_(2026)_hindi_dubbed_movie.html">related</a></div>
</body></html>"""

# What the mirror host answers with; the labels are the site's own.
MIRROR_PAGE = """<html><head><title>Eyes 2026 720p HDRip.mp4 — VidCloud</title></head><body>
<a href="https://five.vidcloud.quest/d/RHdOYGhi/watch_online">Watch Online</a>
<a href="https://five.vidcloud.quest/d/RHdOYGhi/sonicboom">Sonicboom</a>
<a href="https://five.vidcloud.quest/d/RHdOYGhi/skydrop">Skydrop (10GBPS)</a>
<a href="https://five.vidcloud.quest/d/RHdOYGhi/telegram">Telegram</a>
<a href="https://five.vidcloud.quest/d/RHdOYGhi/transferit">Transferit</a>
<a href="https://five.vidcloud.quest/d/RHdOYGhi/gofile">Gofile</a>
<a href="https://five.vidcloud.quest/d/RHdOYGhi/buzzheavier">Buzzheavier</a>
<a href="https://five.vidcloud.quest/d/RHdOYGhi/vikingfile">Vikingfile</a>
</body></html>"""

JS_GATE = b"<!DOCTYPE html><html><head><title>Just a moment...</title></head><body>Enable JavaScript</body></html>"

R2_STREAM = ("https://pub-ed8f2391f70d4e78be675eb510d19b89.r2.dev"
             "/Eyes.2026.Atrangii.Full.Hot.Short.Film.720p.HDRip.mp4")

MOVIE_URL = ("https://www.pagalmovies.fit/movie/29591/"
             "Eyes_(2026)_atrangii_full_hot_short_film.html")

SERIES_FIXTURE = """<html><head><title>Game of Thrones Season 8 Pagalmovies</title></head><body>
<div class="Fun"><b>Category:</b> <a href="/movielist/9/Tv_Web_Series_free_Download/default/1.html">Tv Web Series free Download</a></div>
<h1>Game of Thrones - Season 8 (2019) Episodes</h1>
<div class="pm-q-head"><span class="pm-q-badge">480p</span><span class="pm-q-count">2 files</span></div>
<div class="M1"><a class="fileName" href="https://www.pagalmovies.fit/file/3735/Game_of_thrones_s08_ep01_-_kings_landing.mp4.html"><div>Game of Thrones S08 EP01 - Kings Landing.mp4<br/><span>File Size: 265.5 mb</span></div></a></div>
<div class="M1"><a class="fileName" href="https://www.pagalmovies.fit/file/3736/Game_of_thrones_s08_ep02_-_a_knight_of_the_seven_kingdoms.mp4.html"><div>Game of Thrones S08 EP02 - A Knight of the Seven Kingdoms.mp4<br/><span>File Size: 254 mb</span></div></a></div>
</body></html>"""

HOMEPAGE_FIXTURE = """<html><head><title>PagalMovies 2026 - Download Bollywood,Hollywood,English Dubbed Movies</title></head>
<body><h1 class="subox">PagalMovies 2026 - Download Bollywood Hollywood Movies</h1></body></html>"""

# Taken from a live page (movie/2005) whose film has no genre rows at all.
PLACEHOLDER_GENRE_FIXTURE = FIXTURE.replace(
    '<div class="Fun"><b>Genre:</b> <a href="https://www.pagalmovies.fit/genre/Erotic/1.html">'
    '<i>Erotic</i></a>, <a href="https://www.pagalmovies.fit/genre/Romance/1.html">'
    '<i>Romance</i></a></div>',
    '<div class="Fun"><b>Genre:</b> <a href="https://www.pagalmovies.casa/genre/N/A/1.html">'
    '<i><font color="#7B68EE"><b>N/A</b></font></i></a></div>')


def fake_download_chain(url, referer=None, timeout=25):
    """Models /download/<id> -> /download/<id>/vidcloud -> mirror host."""
    if url.endswith("/download/21801"):
        return 302, "https://www.pagalmovies.fit/download/21801/vidcloud", ""
    if url.endswith("/download/21801/vidcloud"):
        return 302, "https://five.vidcloud.quest/s/RHdOYGhi", ""
    if url.startswith("https://five.vidcloud.quest/s/RHdOYGhi"):
        return 200, None, MIRROR_PAGE
    if url.endswith("/download/3735"):
        return 302, "https://www.pagalmovies.fit/", ""  # the site refused our referer
    return 404, None, ""


class TestTitleCleaning(unittest.TestCase):
    def test_h1_title_is_cleaned_of_packaging(self):
        got = pm.parse_title("Eyes (2026) Atrangii Full Hot Short Film",
                             "Eyes_(2026)_atrangii_full_hot_short_film")
        self.assertEqual(got["clean_title"], "Eyes")
        self.assertEqual(got["year"], 2026)
        self.assertEqual(got["canonical_key"], "eyes_2026")

    def test_season_and_episode_read_from_the_file_name(self):
        got = pm.parse_title("Game of Thrones - Season 8 (2019) Episodes",
                             "Game_of_thrones_-_season_8_(2019)_episodes")
        self.assertEqual(got["clean_title"], "Game of Thrones - Season 8")
        self.assertEqual(got["season_number"], 8)
        self.assertTrue(got["canonical_key"].startswith("game-of-thrones_2019_s08"))
        self.assertEqual(got["media_type"], "complete_season")

    def test_two_slug_variants_of_one_film_share_a_key(self):
        """The site re-publishes with a corrected typo; the row must not strand."""
        a = pm.build_canonical_key("Eyes", 2026, None, None,
                                   "Eyes_(2026)_atrangi_full_hot_short_film")
        b = pm.build_canonical_key("Eyes", 2026, None, None,
                                   "Eyes_(2026)_atrangii_full_hot_short_film")
        self.assertEqual(a, b)

    def test_numeric_titles_survive_the_right_trim(self):
        self.assertEqual(pm._slug_title_base("Jailer_2_(2026)_hindi_dubbed_movie"),
                         "jailer-2")
        self.assertEqual(pm._slug_title_base("3_idiots_(2009)_movie"), "3-idiots")

    def test_alternate_title_in_brackets_is_kept(self):
        got = pm.parse_title("Raj Mahal 3 (Dhilluku Dhuddu) (2026) Movie", "x")
        self.assertIn("Dhilluku Dhuddu", got["clean_title"])

    def test_empty_brackets_left_by_a_year_do_not_pollute_the_title(self):
        got = pm.parse_title("Matargashti (2026) (Hindi) Movie", "matargashti_2026_hindi_movie")
        self.assertEqual(got["clean_title"], "Matargashti")


class TestAuditHygiene(unittest.TestCase):
    """The six defects the full-staging audit found in the first shipped version."""

    def test_a_film_named_for_a_year_keeps_its_name(self):
        for title, year in (("1922 (2017) English Movie", 2017),
                            ("1917 (2019) English Movie", 2019),
                            ("2018 (2023) Tamil Movie", 2023)):
            got = pm.parse_title(title, title.lower().replace(" ", "_"))
            with self.subTest(title=title):
                self.assertEqual(got["clean_title"], title.split(" (")[0])
                self.assertEqual(got["year"], year)

    def test_the_bracketed_year_outranks_a_bare_one(self):
        """The packaging marks where the name ends; the name may itself be a year."""
        got = pm.parse_title("1922 (2017) English Movie", "")
        self.assertEqual(got["year"], 2017)

    def test_a_descriptor_that_opens_the_title_is_part_of_the_name(self):
        self.assertEqual(pm.parse_title("Dual (2025) Hindi Movie", "")["clean_title"], "Dual")
        self.assertEqual(
            pm.parse_title("Complete Unknown (2016) English Movie", "")["clean_title"],
            "Complete Unknown")

    def test_the_title_fallback_keeps_the_site_case(self):
        got = pm.parse_title("(2020) Hindi Dubbed Full Movie", "The_Frozen_North")
        self.assertEqual(got["clean_title"], "The Frozen North")

    def test_an_unclosed_site_bracket_does_not_hang_off_the_title(self):
        got = pm.parse_title("The Return Of Jafar - Aladin 2 (1994 Hindi Dubbed Movie", "x")
        self.assertEqual(got["clean_title"], "The Return Of Jafar - Aladin 2")

    def test_a_bracketed_pseudo_year_is_neither_a_year_nor_a_name(self):
        got = pm.parse_title("Pagal Premi (20012) Bhojpuri Full Movie",
                             "Pagal_premi_(20012)_bhojpuri_full_movie")
        self.assertIsNone(got["year"])
        self.assertNotIn("20012", got["clean_title"])

    def test_the_live_origin_is_queued_and_the_old_one_still_belongs(self):
        self.assertTrue(pm.BASE_URL.endswith(".casa"), pm.BASE_URL)
        self.assertTrue(pm.SITEMAP_URL.startswith(pm.BASE_URL))
        for host in ("https://www.pagalmovies.casa/movie/1/x.html",
                     "https://www.pagalmovies.fit/movie/1/x.html"):
            self.assertTrue(pm._is_site_url(host), host)
        self.assertFalse(pm._is_site_url("https://pagalmovies-copy.example.com/movie/1/x.html"))


class TestSizeParsing(unittest.TestCase):
    def test_site_writes_both_cases_and_commas(self):
        self.assertEqual(pm.parse_size_to_bytes("329.113 MB"), int(329.113 * 1024 ** 2))
        self.assertEqual(pm.parse_size_to_bytes("265.5 mb"), int(265.5 * 1024 ** 2))
        self.assertEqual(pm.parse_size_to_bytes("1.21 GB"), int(1.21 * 1024 ** 3))
        self.assertIsNone(pm.parse_size_to_bytes(None))
        self.assertIsNone(pm.parse_size_to_bytes("n/a"))

    def test_a_size_below_one_file_is_the_site_placeholder(self):
        """No tier of a feature is measured in bytes; those rows carry no size."""
        for text in ("0.000 MB", "-1.000 B", "0.000 B", "753.000 B", "1.499 KB", "0 KB"):
            with self.subTest(text=text):
                self.assertIsNone(pm.parse_size_to_bytes(text))


class TestAdultFlagging(unittest.TestCase):
    def test_shelf_labels_flag_adult_content(self):
        self.assertTrue(pm.is_adult_content("Eyes (2026) Atrangii Full Hot Short Film",
                                           "Hot Short Films", "Erotic, Romance"))
        self.assertTrue(pm.is_adult_content("Some Film", "Brazzers Originals"))
        self.assertTrue(pm.is_adult_content("Title", "", "", "18+"))

    def test_mainstream_labels_are_not_flagged(self):
        self.assertFalse(pm.is_adult_content("Gods Own Country (2014) Movie",
                                            "Malayalam Movies", "Drama"))
        self.assertFalse(pm.is_adult_content("Game of Thrones - Season 8",
                                            "Tv Web Series free Download", "Action"))

    def test_ambiguous_words_in_prose_do_not_flag(self):
        """An 18+ row is hidden everywhere; a blurb must not delete a title."""
        blurb = ("A bold, sensual story of lust and temptation in a Lucknow colony, "
                 "with adult themes handled delicately.")
        self.assertFalse(pm.is_adult_content("Dil Padosi S01", "Drama, Romance",
                                            prose=(blurb,)))
        self.assertTrue(pm.is_adult_content("Dil Padosi S01", "Adult, Drama"))


class TestBrandScrubbing(unittest.TestCase):
    def test_site_and_sister_brands_are_removed(self):
        for token in ("Pagalmovies", "PAGALMOVIES 2026", "filmyhit", "coolmoviez",
                      "allmovieland", "mp4movies"):
            self.assertNotIn(token.split()[0].lower(), pm.scrub_brand(token).lower())

    def test_a_real_title_is_not_eaten_by_the_scrubber(self):
        self.assertEqual(pm.scrub_brand("The Pagal Paradox"), "The Pagal Paradox")


class TestLinkHarvesting(unittest.TestCase):
    def test_files_carry_the_quality_heading_above_them(self):
        files = pm.harvest_files(MOVIE_URL, FIXTURE)
        self.assertEqual([f["quality"] for f in files], ["720p", "1080p"])
        self.assertEqual([f["file_id"] for f in files], ["21801", "21800"])
        self.assertEqual(files[0]["size_text"], "329.113 MB")

    def test_provider_mirrors_are_read_with_their_labels(self):
        mirrors = pm.harvest_mirrors(MIRROR_PAGE)
        by_provider = {m["provider"]: m for m in mirrors}
        self.assertIn("watch_online", by_provider)
        self.assertIn("skydrop", by_provider)
        self.assertIn("gofile", by_provider)
        self.assertEqual(by_provider["skydrop"]["token"], "RHdOYGhi")
        self.assertEqual(by_provider["watch_online"]["label"], "Watch Online")

    def test_mirrors_are_not_duplicated(self):
        mirrors = pm.harvest_mirrors(MIRROR_PAGE + MIRROR_PAGE)
        self.assertEqual(len(mirrors), 8)


class TestParsePage(unittest.TestCase):
    def test_fixture_page_yields_a_staging_shaped_post(self):
        with mock.patch.object(pm, "http_get", return_value=(200, MOVIE_URL, FIXTURE)):
            post = pm.parse_page(MOVIE_URL)
        self.assertEqual(post["clean_title"], "Eyes")
        self.assertEqual(post["year"], 2026)
        self.assertEqual(post["source_site"], "pagalmovies")
        self.assertEqual(post["is_18_plus"], 1)
        self.assertEqual(post["genres"], "Erotic, Romance")
        self.assertEqual(len(post["releases"]), 2)
        self.assertEqual(post["poster_url"],
                         "https://www.pagalmovies.fit/files/images/"
                         "Eyes_(2026)_Atrangii_Full_Hot_Short_Film.jpg")

    def test_placeholder_metadata_is_stored_as_null(self):
        with mock.patch.object(pm, "http_get", return_value=(200, MOVIE_URL, FIXTURE)):
            post = pm.parse_page(MOVIE_URL)
        self.assertIsNone(post["synopsis"])
        self.assertIsNone(post["cast_names"])
        self.assertIsNone(post["duration"])

    def test_a_redirect_to_the_homepage_is_not_a_catalog_entry(self):
        with mock.patch.object(pm, "http_get",
                               return_value=(200, "https://www.pagalmovies.fit/",
                                             HOMEPAGE_FIXTURE)):
            self.assertIsNone(pm.parse_page("https://www.pagalmovies.fit/movie/99/x.html"))

    def test_a_stale_sitemap_id_that_404s_is_skipped(self):
        with mock.patch.object(pm, "http_get", return_value=(404, "", "")):
            self.assertIsNone(pm.parse_page("https://www.pagalmovies.fit/movie/1/x.html"))

    def test_decline_reasons_let_the_crawler_park_a_gone_page_at_once(self):
        """A 302 to the homepage is final; only a transport error deserves a retry."""
        gone = "https://www.pagalmovies.fit/movie/29650/Cocoons_(2026)_movie.html"
        with mock.patch.object(pm, "http_get", return_value=(200, "https://www.pagalmovies.fit/",
                                                            HOMEPAGE_FIXTURE)):
            self.assertEqual(pm._parse_page(gone)[1], "removed")
        with mock.patch.object(pm, "http_get", return_value=(500, "", "")):
            self.assertEqual(pm._parse_page(gone)[1], "http-500")
        with mock.patch.object(pm, "http_get", return_value=(404, "", "")):
            self.assertEqual(pm._parse_page(gone)[1], "http-404")
        with mock.patch.object(pm, "http_get",
                               return_value=(200, "https://www.pagalmovies.fit/movielist/24/x.html",
                                             HOMEPAGE_FIXTURE)):
            self.assertEqual(pm._parse_page("https://www.pagalmovies.fit/movielist/24/x.html")[1],
                             "not-a-post")
        with mock.patch.object(pm, "http_get", return_value=(200, MOVIE_URL, FIXTURE)):
            post, verdict = pm._parse_page(MOVIE_URL)
        self.assertEqual(verdict, "ok")
        self.assertIsNotNone(post)

    def test_the_sites_own_release_date_outranks_its_seo_title_year(self):
        """The site titles "The 40 Year Old Virgin (1965)" and dates it 19 August,2005."""
        body = FIXTURE.replace("<b>Release Date:</b>", "<b>Release Date:</b> 19 August,2005 <b>x:</b>")
        with mock.patch.object(pm, "http_get", return_value=(200, MOVIE_URL, body)):
            post = pm.parse_page(MOVIE_URL)
        self.assertEqual(post["year"], 2005)

    def test_episodes_become_releases_and_a_season_map(self):
        with mock.patch.object(pm, "http_get",
                               return_value=(200, "https://www.pagalmovies.fit/movie/2897/"
                                             "Game_of_thrones_-_season_8_(2019)_episodes.html",
                                             SERIES_FIXTURE)):
            post = pm.parse_page("https://www.pagalmovies.fit/movie/2897/"
                                 "Game_of_thrones_-_season_8_(2019)_episodes.html")
        self.assertEqual(post["content_type"], "complete_season")
        self.assertEqual(sorted(r["episode_number"] for r in post["releases"]), [1, 2])
        seasons = json.loads(post["seasons"])
        self.assertEqual(seasons[0]["season"], 8)
        self.assertEqual([e["episode"] for e in seasons[0]["episodes"]], [1, 2])

    def test_unprobed_files_keep_a_bridge_row_with_an_honest_status(self):
        with mock.patch.object(pm, "http_get", return_value=(200, MOVIE_URL, FIXTURE)):
            post = pm.parse_page(MOVIE_URL)
        src = post["releases"][0]["sources"][0]
        self.assertEqual(src["status"], "unknown")
        self.assertEqual(src["source_url"], f"{pm.BASE_URL}/download/21801")

    def test_the_site_placeholder_genre_link_is_not_a_genre(self):
        """Live pages publish <a>...<b>N/A</b></a> as the only genre of a title."""
        with mock.patch.object(pm, "http_get",
                               return_value=(200, MOVIE_URL, PLACEHOLDER_GENRE_FIXTURE)):
            post = pm.parse_page(MOVIE_URL)
        self.assertIsNone(post["genres"])

    def test_the_updated_webseries_strip_is_not_this_posts_metadata(self):
        with mock.patch.object(pm, "http_get", return_value=(200, MOVIE_URL, FIXTURE)):
            post = pm.parse_page(MOVIE_URL)
        block = post["raw_meta"]["info_block"]
        self.assertNotIn("updated webseries", block)
        self.assertNotIn("Hunkkaar", json.dumps(post["raw_meta"], ensure_ascii=False))


class TestResolveLinks(unittest.TestCase):
    def _post(self):
        with mock.patch.object(pm, "http_get", return_value=(200, MOVIE_URL, FIXTURE)):
            return pm.parse_page(MOVIE_URL)

    def test_chain_walk_stores_every_provider(self):
        with mock.patch.object(pm, "http_get_once", side_effect=fake_download_chain):
            post = pm.resolve_links(self._post(), probe=True)
        services = [s["service"] for s in post["releases"][0]["sources"]]
        self.assertEqual(len(services), 8)
        self.assertIn("skydrop", services)
        self.assertIn("watch_online", services)

    def test_deep_walk_unwraps_the_playable_and_the_signed_cdn(self):
        def chain(url, referer=None, timeout=25):
            if url.endswith("/download/21800"):
                return 302, "https://www.pagalmovies.fit/download/21800/vidcloud", ""
            return fake_download_chain(url, referer, timeout)

        with mock.patch.object(pm, "http_get_once", side_effect=chain), \
             mock.patch.object(pm, "_final_cdn_target",
                               return_value=("stream", R2_STREAM, "active")):
            post = pm.resolve_links(self._post(), probe=True, deep=True)
        by_service = {s["service"]: s for s in post["releases"][0]["sources"]}
        self.assertEqual(by_service["watch_online"]["final_url"], R2_STREAM)
        self.assertEqual(by_service["watch_online"]["playback_type"], "stream")
        self.assertEqual(by_service["watch_online"]["status"], "active")

    def test_a_gone_download_row_is_recorded_as_dead_not_blocked(self):
        """Old files answer the framework error page; that is a dead link."""
        def gone(url, referer=None, timeout=25):
            return 503, None, "<html><head><title>Error</title></head><body>Unable</body></html>"

        post = self._post()
        for release in post["releases"]:
            release["download_id"] = "60"
        with mock.patch.object(pm, "http_get_once", side_effect=gone):
            post = pm.resolve_links(post, probe=True)
        src = post["releases"][0]["sources"][0]
        self.assertEqual(src["status"], "dead")
        self.assertEqual(src["service"], "bridge")

    def test_a_referer_refused_link_is_recorded_as_blocked_not_dropped(self):
        """Without an on-site Referer the site bounces to its homepage: a wall, not a dead end."""
        with mock.patch.object(pm, "http_get_once", side_effect=fake_download_chain):
            self.assertEqual(pm._walk_download("3735", None)[0], "blocked")
            self.assertEqual(pm._walk_download("3735", MOVIE_URL)[0], "dead")

    def test_a_js_gate_is_recorded_as_js_required(self):
        def gated(url, referer=None, timeout=25):
            return 503, None, JS_GATE.decode()

        with mock.patch.object(pm, "http_get_once", side_effect=gated):
            post = pm.resolve_links(self._post(), probe=True)
        self.assertEqual(post["releases"][0]["sources"][0]["status"], "js_required")

    def test_probe_off_leaves_the_bridge_row_untouched(self):
        post = pm.resolve_links(self._post(), probe=False)
        self.assertEqual(post["releases"][0]["sources"][0]["status"], "unknown")

    def test_download_walk_reports_the_vidcloud_page(self):
        with mock.patch.object(pm, "http_get_once", side_effect=fake_download_chain):
            outcome, page, body = pm._walk_download("21801", MOVIE_URL)
        self.assertEqual(outcome, "ok")
        self.assertIn("five.vidcloud.quest/s/RHdOYGhi", page)
        self.assertIn("skydrop", body)


class TestStagingDatabase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = Path(self.tmp) / "pagalmovies.db"
        with mock.patch.object(pm, "http_get", return_value=(200, MOVIE_URL, FIXTURE)):
            self.post = pm.parse_page(MOVIE_URL)

    def test_writes_the_isolated_staging_file_only(self):
        out = pm.export_staging(self.db, [self.post])
        self.assertEqual(out["posts_written"], 1)
        self.assertEqual(out["releases_written"], 2)
        self.assertTrue(self.db.exists())

    def test_recrawl_is_idempotent(self):
        pm.export_staging(self.db, [self.post])
        pm.export_staging(self.db, [self.post])
        conn = sqlite3.connect(self.db)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0], 1)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM releases").fetchone()[0], 2)
        conn.close()

    def test_two_pages_of_one_title_keep_their_own_prints(self):
        """A pack page and a season page must not delete each other's releases."""
        first = dict(self.post, url=MOVIE_URL)
        second = dict(self.post, url="https://www.pagalmovies.fit/movie/29592/"
                                    "Eyes_(2026)_atrangii_pack.html")
        pm.export_staging(self.db, [first])
        pm.export_staging(self.db, [second])
        conn = sqlite3.connect(self.db)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM releases").fetchone()[0], 4)
        self.assertEqual(conn.execute(
            "SELECT COUNT(DISTINCT origin_url) FROM releases").fetchone()[0], 2)
        conn.close()

    def test_source_row_columns_are_the_ones_the_catalog_reads(self):
        pm.export_staging(self.db, [self.post])
        conn = sqlite3.connect(self.db)
        conn.row_factory = sqlite3.Row
        cols = {c[1] for c in conn.execute("PRAGMA table_info(sources)")}
        for needed in ("source_name", "service", "resource_id", "source_url",
                       "final_url", "playback_type", "is_temporary", "status"):
            self.assertIn(needed, cols)
        conn.close()

    def test_no_provenance_token_reaches_a_display_column(self):
        pm.export_staging(self.db, [self.post])
        conn = sqlite3.connect(self.db)
        row = conn.execute("SELECT title, clean_title, synopsis, genres FROM posts").fetchone()
        joined = " ".join(str(v) for v in row).lower()
        for needle in ("pagalmovies", "filesdl", "vidcloud", "bit.ly", "agl002",
                       "allmovieland", "coolmoviez", "filmyhit"):
            self.assertNotIn(needle, joined)
        conn.close()

    def test_stats_and_status_counts(self):
        pm.export_staging(self.db, [self.post])
        st = pm.stats(self.db)
        self.assertEqual(st["posts"], 1)
        self.assertEqual(st["releases"], 2)
        self.assertEqual(st["adult_flagged"], 1)
        self.assertEqual(st["source_status"], {"unknown": 2})


class TestMergeCatalogsContract(unittest.TestCase):
    """merge_catalogs.py must be able to read this staging shape."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = Path(self.tmp) / "pagalmovies.db"
        with mock.patch.object(pm, "http_get", return_value=(200, MOVIE_URL, FIXTURE)):
            post = pm.parse_page(MOVIE_URL)
        pm.export_staging(self.db, [dict(post, releases=[
            dict(post["releases"][0], sources=[dict(
                post["releases"][0]["sources"][0],
                source_name="Skydrop (10GBPS)", service="skydrop",
                resource_id="RHdOYGhi",
                source_url="https://five.vidcloud.quest/d/RHdOYGhi/skydrop",
                final_url="https://five.vidcloud.quest/d/RHdOYGhi/skydrop",
                status="active")])])])

    def test_source_family_is_staging(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        import merge_catalogs
        conn = sqlite3.connect(self.db)
        conn.row_factory = sqlite3.Row
        self.assertEqual(merge_catalogs._source_family(conn), "staging")
        conn.close()

    def test_collected_post_carries_the_site_and_its_mirrors(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        import merge_catalogs
        conn = sqlite3.connect(self.db)
        conn.row_factory = sqlite3.Row
        post_row = conn.execute("SELECT * FROM posts").fetchone()
        collected = merge_catalogs._collect_staging_post(conn, post_row, "pagalmovies")
        conn.close()
        self.assertEqual(collected["source_site"], "pagalmovies")
        self.assertEqual(collected["canonical_key"], "eyes_2026")
        self.assertEqual(collected["content_type"], "movie")
        self.assertEqual(len(collected["releases"]), 1)
        mirror = collected["releases"][0]["sources"][0]
        self.assertEqual(mirror["service"], "skydrop")
        self.assertEqual(mirror["status"], "active")
        self.assertEqual(collected["releases"][0]["quality"], "720p")
        self.assertEqual(collected["releases"][0]["size"], "329.11 MB")


class TestSyncCatalog(unittest.TestCase):
    INDEX = ('<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/'
             'schemas/sitemap/0.9"><sitemap><loc>https://www.pagalmovies.fit/'
             'sitemap-movies-1.xml</loc></sitemap></sitemapindex>')
    URLSET = ('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
              '<url><loc>https://www.pagalmovies.fit/movie/6/Gods_own_country_'
              '(2014)_movie.html</loc></url>'
              '<url><loc>https://www.pagalmovies.fit/movie/29638/Hung_up_on_alina_'
              '&amp;_the_saga_(2026)_movie.html</loc></url>'
              '<url><loc>https://www.pagalmovies.fit/movielist/14/Bollywood_movies/'
              'default/1.html</loc></url>'
              '<url><loc>https://www.pagalmovies.fit/services/disclaimer.html</loc></url>'
              '</urlset>')

    def test_index_is_followed_and_shelves_are_skipped(self):
        tmp = Path(tempfile.mkdtemp()) / "pagalmovies.db"

        def get(url, timeout=30, retries=3):
            return (200, url, self.INDEX if url.endswith("/sitemap.xml") else self.URLSET)

        with mock.patch.object(pm, "http_get", side_effect=get):
            added = pm.sync_catalog(db_path=tmp)
        self.assertEqual(added, 2)
        conn = sqlite3.connect(tmp)
        locs = [r[0] for r in conn.execute("SELECT loc FROM sitemap_cache").fetchall()]
        conn.close()
        self.assertTrue(all("/movie/" in l for l in locs))
        self.assertIn("Hung_up_on_alina_&_the_saga_(2026)_movie.html",
                      [l.split("/")[-1] for l in locs])

    def test_a_missing_child_sitemap_does_not_abort_the_run(self):
        tmp = Path(tempfile.mkdtemp()) / "pagalmovies.db"

        def get(url, timeout=30, retries=3):
            if url.endswith("/sitemap.xml"):
                return 200, url, self.INDEX.replace(
                    "sitemap-movies-1", "sitemap-movies-5")
            return 404, url, ""

        with mock.patch.object(pm, "http_get", side_effect=get):
            self.assertEqual(pm.sync_catalog(db_path=tmp), 0)

    def test_resync_does_not_reset_indexed_pages(self):
        tmp = Path(tempfile.mkdtemp()) / "pagalmovies.db"
        get = mock.Mock(return_value=(200, tmp.as_uri(), self.URLSET))
        with mock.patch.object(pm, "http_get", side_effect=lambda u, **k:
                               (200, u, self.INDEX if u.endswith("/sitemap.xml")
                                else self.URLSET)):
            pm.sync_catalog(db_path=tmp)
        conn = sqlite3.connect(tmp)
        conn.execute("UPDATE sitemap_cache SET scraped = 1")
        conn.commit()
        conn.close()
        with mock.patch.object(pm, "http_get", side_effect=lambda u, **k:
                               (200, u, self.INDEX if u.endswith("/sitemap.xml")
                                else self.URLSET)):
            again = pm.sync_catalog(db_path=tmp)
        self.assertEqual(again, 0)


class TestSignalSafety(unittest.TestCase):
    def test_stop_flag_is_honoured_by_the_worker(self):
        pm.STOP_REQUESTED = True
        try:
            with mock.patch.object(pm, "_parse_page") as parse:
                totals = pm.crawl_pending(db_path=Path(tempfile.mkdtemp()) / "x.db",
                                          workers=1, verbose=False)
        finally:
            pm.STOP_REQUESTED = False
        self.assertEqual(totals["pages"], 0)
        parse.assert_not_called()


class TestCrawlQueue(unittest.TestCase):
    """Half the sitemap ids this site publishes are gone; the queue must say so."""

    def _db_with(self, locs):
        tmp = Path(tempfile.mkdtemp()) / "pagalmovies.db"
        conn = sqlite3.connect(tmp)
        pm.ensure_schema(conn)
        for loc in locs:
            conn.execute("INSERT INTO sitemap_cache (loc, slug, scraped) VALUES (?, ?, 0)",
                         (loc, loc.split("/")[-1]))
        conn.commit()
        conn.close()
        return tmp

    def _states(self, db, loc):
        conn = sqlite3.connect(db)
        row = conn.execute("SELECT scraped, error_count FROM sitemap_cache WHERE loc = ?",
                           (loc,)).fetchone()
        conn.close()
        return row

    def test_a_page_the_site_removed_is_parked_on_the_first_sighting(self):
        gone = f"{pm.BASE_URL}/movie/29650/Cocoons_(2026)_movie.html"
        db = self._db_with([gone])
        with mock.patch.object(pm, "http_get",
                               return_value=(200, f"{pm.BASE_URL}/", HOMEPAGE_FIXTURE)):
            totals = pm.crawl_pending(db_path=db, workers=1, verbose=False)
        self.assertEqual(totals["not_indexable"], 1)
        self.assertEqual(self._states(db, gone), (-1, 1))

    def test_a_transport_error_is_retried_rather_than_parked(self):
        flaky = f"{pm.BASE_URL}/movie/29651/Flaky_(2026)_movie.html"
        db = self._db_with([flaky])
        with mock.patch.object(pm, "http_get", return_value=(500, "", "")):
            pm.crawl_pending(db_path=db, workers=1, verbose=False)
        self.assertEqual(self._states(db, flaky), (0, 1))

    def test_a_hard_404_is_the_sites_answer_and_parks_at_once(self):
        gone = f"{pm.BASE_URL}/movie/29652/Gone_(2026)_movie.html"
        db = self._db_with([gone])
        with mock.patch.object(pm, "http_get", return_value=(404, "", "")):
            totals = pm.crawl_pending(db_path=db, workers=1, verbose=False)
        self.assertEqual(self._states(db, gone), (-1, 1))
        self.assertEqual(totals["declined_by_reason"], {"http-404": 1})

    def test_the_third_transport_failure_parks_the_row(self):
        """Retry must be capped, or a permanently 500 page is retried forever."""
        bad = f"{pm.BASE_URL}/movie/29653/Bad_(2026)_movie.html"
        db = self._db_with([bad])
        with mock.patch.object(pm, "http_get", return_value=(503, "", "")):
            for _ in range(3):
                pm.crawl_pending(db_path=db, workers=1, verbose=False)
        self.assertEqual(self._states(db, bad), (-1, 3))


if __name__ == "__main__":
    unittest.main(verbosity=2)
