#!/usr/bin/env python3
"""
test_moviesmela_import.py — offline unit tests for the moviesmela staging importer.

No test here reaches the network: both fetch seams delegate to one injectable
call (`_open`), so the retry loop, the gate short-circuit and the
redirect-reporting path run for real, and `socket.socket` is replaced for the
whole suite so a leak fails loudly instead of hanging. Fixtures are shaped from
live www.moviesmela.com payloads captured 2026-10-28 — the REST record, the four
iframe players, the Yoast og_image, the real category vocabulary.

The rule this suite exists to keep: an iframe is stored as an iframe with an
honest status, and never becomes a playable byte endpoint.
"""

from __future__ import annotations

import contextlib
import io
import json
import runpy
import signal
import socket
import sqlite3
import sys
import tempfile
import threading
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import import_moviesmela as mm  # noqa: E402


class _NoLiveSocket:
    def __init__(self, *args, **kwargs):
        raise AssertionError("offline suite attempted a live connection")


socket.socket = _NoLiveSocket


@contextlib.contextmanager
def silenced():
    buf = io.StringIO()
    with contextlib.ExitStack() as stack:
        for stream in ("stdout", "stderr"):
            stack.enter_context(mock.patch.object(sys, stream, buf))
        yield buf


CONTENT = (
    "<h2>Watch Haiwaan (2026) Hindi From Player 1 Below </h2>\n"
    '<p><iframe loading="lazy" width="640" height="360" '
    'src="//ok.ru/videoembed/16335355447893?nochat=1" frameborder="0" '
    'allow="autoplay" allowfullscreen></iframe></p>\n'
    "<h2>Watch Haiwaan (2026) Hindi From Player 2 Below </h2>\n"
    '<p><iframe SRC="https://pkembed.site/embed-eop0bc6zkyjy.html" '
    "FRAMEBORDER=0 WIDTH=640 HEIGHT=360 allowfullscreen></iframe></p>\n"
    "<h2>Watch Haiwaan (2026) Hindi From Player 3 Below </h2>\n"
    '<p><iframe loading="lazy" width="640" height="360" '
    'src="https://do7go.com/e/so6dywi0047l" scrolling="no" frameborder="0" '
    'allowfullscreen="true"></iframe></p>\n'
    "<h2>Watch Haiwaan (2026) Hindi From Player 4 Below </h2>\n"
    '<p><iframe loading="lazy" width="640" height="360" '
    'src="//mxdrop.to/e/7kk0mpgdsmoqd4" scrolling="no" frameborder="0" '
    'allowfullscreen="true"></iframe><br />\n'
    "Haiwaan (2026) Hindi Full Movie Watch Online HD Print Free Download,"
    "Full Movie Haiwaan (2026) Hindi Watch Online DVD Download.</p>\n"
)

SLUG = "haiwaan-2026-hindi-full-movie-watch-online-hd-print-free-download"
LINK = f"https://www.moviesmela.com/{SLUG}/"

TAXONOMY = {2582: "2026 Movies", 2: "Indian Movies", 962: "Watch Bollywood Movies Online",
            719: "Hindi Dubbed Movies", 720: "Urdu Dubbed Movies", 1523: "Hollywood Movies",
            54: "English Movies", 55: "Watch Full Punjabi Movies Online",
            2432: "South Indian Dubbed Hindi", 2509: "Animated Hindi Movies",
            2536: "Shows / Series", 2505: "Seasons / WebSeries",
            2583: "Bigg Boss Season 20", 15: "Akshay Kumar Movies List",
            30: "sanjay dutt movies list", 60: "Horror Movies", 3: "action movies",
            1028: "Articles", 2567: "Slot Oyna", 1324: "Wrestling Videos",
            2433: "Tiger Shroff"}


def wp_post(**over) -> dict:
    record = {
        "id": 439845,
        "slug": SLUG,
        "link": LINK,
        "title": {"rendered": "Haiwaan (2026) Hindi Full Movie "
                              "Watch Online HD Print Free Download"},
        "excerpt": {"rendered": "<p>Watch Haiwaan (2026) Hindi From Player 1 Below</p>"},
        "content": {"rendered": CONTENT},
        "date": "2026-10-28T00:21:20",
        "modified": "2026-10-28T00:21:20",
        "categories": [2582, 2, 962],
        "tags": [62],
        "yoast_head_json": {
            "og_image": [{"url": "https://www.moviesmela.com/wp-content/uploads/"
                                 "2026/10/Haiwaan-2026-Hindi.jpg", "width": 200}],
            "og_description": "Haiwaan (2026) Hindi Full Movie Watch Online HD "
                              "Print Free Download,Full Movie Haiwaan (2026) "
                              "Hindi Watch Online DVD Download.",
            "title": "Haiwaan (2026) Hindi Full Movie Watch Online HD Print Free Download",
        },
    }
    record.update(over)
    return record


class FakeResponse:
    def __init__(self, body: bytes = b"", status: int = 200):
        self._body = body
        self.status = status

    def read(self, _limit: int = -1):
        return self._body if _limit < 0 else self._body[:_limit]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def fake_open(responses):
    """An `_open` stand-in: pops one canned outcome per call."""
    calls = []

    def _open(request, follow=True, timeout=30):
        calls.append((request, follow, timeout))
        outcome = responses[min(len(calls) - 1, len(responses) - 1)]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome
    _open.calls = calls
    return _open


class TestSeams(unittest.TestCase):
    def test_open_picks_the_redirect_opener(self):
        """`_open` itself, not a patch of it: the two openers are the whole seam."""
        seen = []

        class Opener:
            def __init__(self, name):
                self.name = name

            def open(self, request, timeout):
                seen.append((self.name, timeout))
                return FakeResponse(b"body", 200)

        with mock.patch.object(mm, "_OPENER", Opener("follow")), \
                mock.patch.object(mm, "_NO_REDIRECT_OPENER", Opener("strict")):
            with mm._open(urllib.request.Request("https://x.test/a"), timeout=9):
                pass
            with mm._open(urllib.request.Request("https://x.test/a"), timeout=9,
                          follow=False):
                pass
        self.assertEqual(seen, [("follow", 9), ("strict", 9)])

    def test_stop_redirect_handler_reports_instead_of_following(self):
        self.assertIsNone(mm._StopRedirect().redirect_request(
            urllib.request.Request("https://x.test/a"), None, 302, "Found",
            {}, "https://x.test/b"))


    def test_http_get_returns_body_and_status(self):
        with mock.patch.object(mm, "_open", fake_open([FakeResponse(b"hello", 200)])):
            self.assertEqual(mm.http_get("https://x.test/a"), (200, "hello"))

    def test_http_get_retries_then_succeeds(self):
        opener = fake_open([
            OSError("timed out"),
            urllib.error.URLError("no route"),
            FakeResponse(b"ok", 200),
        ])
        with mock.patch.object(mm, "_open", opener), \
                mock.patch.object(mm, "_sleep") as nap:
            status, body = mm.http_get("https://x.test/a", retries=3)
        self.assertEqual((status, body), (200, "ok"))
        self.assertEqual(nap.call_count, 2)
        self.assertEqual(len(opener.calls), 3)

    def test_http_get_returns_http_error_immediately(self):
        err = urllib.error.HTTPError("https://x.test/a", 403, "Forbidden", None, None)
        with mock.patch.object(mm, "_open", fake_open([err])):
            self.assertEqual(mm.http_get("https://x.test/a"), (403, ""))

    def test_http_get_generic_exception_short_circuits(self):
        with mock.patch.object(mm, "_open", fake_open([ValueError("boom")])):
            self.assertEqual(mm.http_get("https://x.test/a"), (0, "ValueError: boom"))

    def test_http_get_exhausts_retries_with_transport_error(self):
        with mock.patch.object(mm, "_open", fake_open([TimeoutError("slow")])), \
                mock.patch.object(mm, "_sleep"):
            status, body = mm.http_get("https://x.test/a", retries=2)
        self.assertEqual(status, 0)
        self.assertIn("TimeoutError", body)

    def test_http_get_stops_when_signalled(self):
        with mock.patch.object(mm, "STOP_REQUESTED", True), \
                mock.patch.object(mm, "_open", fake_open([FakeResponse(b"x")])):
            self.assertEqual(mm.http_get("https://x.test/a"), (0, ""))

    def test_http_get_once_follows_no_redirect(self):
        with mock.patch.object(mm, "_open", fake_open([FakeResponse(b"player", 200)])):
            status, body, location = mm.http_get_once("https://mxdrop.to/e/x")
        self.assertEqual((status, body, location), (200, "player", ""))

    def test_http_get_once_reports_redirect_location(self):
        headers = {"Location": "https://mxdrop.top/e/x"}
        err = urllib.error.HTTPError("https://mxdrop.to/e/x", 302, "Found", headers, None)
        with mock.patch.object(mm, "_open", fake_open([err])):
            self.assertEqual(mm.http_get_once("https://mxdrop.to/e/x"),
                             (302, "", "https://mxdrop.top/e/x"))

    def test_http_get_once_reads_error_body(self):
        err = urllib.error.HTTPError("https://x.test/e", 403, "Forbidden", {}, None)
        err.read = lambda _n=-1: b"Verify You Are Human"
        with mock.patch.object(mm, "_open", fake_open([err])):
            status, body, location = mm.http_get_once("https://x.test/e")
        self.assertEqual((status, location), (403, ""))
        self.assertIn("Human", body)

    def test_http_get_once_error_body_unreadable(self):
        err = urllib.error.HTTPError("https://x.test/e", 500, "Boom", {}, None)

        def explode(_n=-1):
            raise OSError("closed")
        err.read = explode
        with mock.patch.object(mm, "_open", fake_open([err])):
            self.assertEqual(mm.http_get_once("https://x.test/e"), (500, "", ""))

    def test_http_get_once_referer_is_sent(self):
        opener = fake_open([FakeResponse(b"ok", 200)])
        with mock.patch.object(mm, "_open", opener):
            mm.http_get_once("https://x.test/e", referer="https://www.moviesmela.com/")
        request = opener.calls[0][0]
        self.assertEqual(request.get_header("Referer"), "https://www.moviesmela.com/")
        self.assertFalse(opener.calls[0][1])

    def test_http_get_once_transport_failure(self):
        with mock.patch.object(mm, "_open", fake_open([OSError("reset by peer")])):
            status, body, location = mm.http_get_once("https://x.test/e")
        self.assertEqual((status, body), (0, ""))
        self.assertIn("OSError", location)

    def test_get_json_parses_body(self):
        with mock.patch.object(mm, "http_get", return_value=(200, '[{"id": 1}]')):
            self.assertEqual(mm.get_json("https://x.test/j"), (200, [{"id": 1}]))

    def test_get_json_treats_empty_body_as_no_payload(self):
        # measured on this host: 200 + content-length: 0 for per_page=20&_embed=1
        with mock.patch.object(mm, "http_get", return_value=(200, "  ")):
            self.assertEqual(mm.get_json("https://x.test/j"), (200, None))

    def test_get_json_survives_html_answer(self):
        with mock.patch.object(mm, "http_get", return_value=(200, "<html>gate</html>")):
            self.assertEqual(mm.get_json("https://x.test/j"), (200, None))

    def test_get_json_passes_non_200_through(self):
        with mock.patch.object(mm, "http_get", return_value=(500, "")):
            self.assertEqual(mm.get_json("https://x.test/j"), (500, None))

    def test_builders_make_two_openers(self):
        # Both openers come from callables, so there is no import-time socket in
        # this module and the tests can build either branch.
        ctx = mm._build_ssl_context()
        jar = __import__("http.cookiejar", fromlist=["CookieJar"]).CookieJar()
        following, stopping = mm._build_openers(ctx, jar)
        self.assertIsNotNone(following)
        self.assertIsNotNone(stopping)


class TestTextHelpers(unittest.TestCase):
    def test_unescape_and_clean(self):
        self.assertEqual(mm._clean_text("Haiwaan &amp; Co.   <b>"), "Haiwaan & Co. <b>")

    def test_scrub_brand_only_touches_display_strings(self):
        self.assertEqual(mm.scrub_brand("MoviesFlix presents Haiwaan"),
                         "presents Haiwaan")
        self.assertEqual(mm.scrub_brand("Movies Mela - Bigg Boss"), "Bigg Boss")

    def test_normalize_http_url_forms(self):
        self.assertEqual(mm._normalize_http_url("//ok.ru/videoembed/1"),
                         "https://ok.ru/videoembed/1")
        self.assertEqual(mm._normalize_http_url("/x/y"), "https://www.moviesmela.com/x/y")
        self.assertEqual(mm._normalize_http_url("https://a.test/x"), "https://a.test/x")
        self.assertEqual(mm._normalize_http_url("   "), "")

    def test_host_predicates(self):
        self.assertTrue(mm._is_site_url("https://www.moviesmela.com/x/"))
        self.assertFalse(mm._is_site_url("https://moviesmela.com.evil.test/x/"))
        self.assertFalse(mm._is_site_url(""))
        self.assertTrue(mm._is_embed_host("https://mxdrop.to/e/x"))
        self.assertTrue(mm._is_embed_host("https://vkcdn5.foo/embed-x.html"))
        self.assertFalse(mm._is_embed_host("https://adnetwork.test/x"))

    def test_resource_id_shapes(self):
        self.assertEqual(mm._resource_id("https://ok.ru/videoembed/16335355447893?x=1"),
                         "16335355447893")
        self.assertEqual(mm._resource_id("https://pkembed.site/embed-eop0bc6zkyjy.html"),
                         "embed-eop0bc6zkyjy")
        self.assertEqual(mm._resource_id("https://mxdrop.to/e/7kk0mpgdsmoqd4"),
                         "7kk0mpgdsmoqd4")
        self.assertEqual(mm._resource_id("https://x.test/download/file.php"), "file")
        self.assertEqual(mm._resource_id("https://x.test"), "")

    def test_is_temporary(self):
        self.assertEqual(mm._is_temporary("https://x/a?token=1"), 1)
        self.assertEqual(mm._is_temporary("https://x/a"), 0)

    def test_slugify(self):
        self.assertEqual(mm._slugify("The Marvelous Mrs. Maisel"),
                         "the-marvelous-mrs-maisel")
        self.assertEqual(mm._slugify(None), "")

    def test_host_of(self):
        self.assertEqual(mm._host_of("https://OK.RU/video"), "ok.ru")
        self.assertEqual(mm._host_of(""), "")


class TestPlayerParsing(unittest.TestCase):
    def test_four_players_in_site_order(self):
        rows = mm.parse_players(CONTENT)
        self.assertEqual([r["source_name"] for r in rows],
                         ["Player 1", "Player 2", "Player 3", "Player 4"])
        self.assertEqual(rows[0]["source_url"],
                         "https://ok.ru/videoembed/16335355447893?nochat=1")
        self.assertEqual(rows[0]["playback_type"], "iframe")
        self.assertEqual(rows[0]["status"], "unverified")
        self.assertEqual({r["service"] for r in rows},
                         {"ok.ru", "pkembed.site", "do7go.com", "mxdrop"})
        by_service = {r["service"]: r for r in rows}
        # mxdrop is the one host this catalog can resolve with pure stdlib, so it
        # is a URL row; the other three are iframes the client cannot play.
        self.assertEqual(by_service["mxdrop"]["playback_type"], "url")
        self.assertEqual(by_service["mxdrop"]["is_temporary"], True)
        self.assertEqual(by_service["pkembed.site"]["playback_type"], "iframe")
        self.assertEqual(by_service["do7go.com"]["is_temporary"], False)
        self.assertEqual(by_service["mxdrop"]["status"], "unverified")

    def test_empty_and_labelless(self):
        self.assertEqual(mm.parse_players(""), [])
        rows = mm.parse_players('<iframe src="https://mxdrop.to/e/abc"></iframe>')
        self.assertEqual(rows[0]["source_name"], "Player 1")

    def test_missing_headings_fall_back_to_position(self):
        rows = mm.parse_players('<h2>x</h2><iframe src="https://ok.ru/videoembed/1">'
                                '</iframe><iframe src="https://mxdrop.to/e/2"></iframe>')
        self.assertEqual([r["source_name"] for r in rows], ["Player 1", "Player 2"])

    def test_blank_src_is_skipped(self):
        self.assertEqual(mm.parse_players('<iframe src=""></iframe>'), [])

    def test_split_players_refuses_unknown_host_but_reports_it(self):
        content = ('<iframe src="https://mxdrop.to/e/ok"></iframe>'
                   '<iframe src="https://adtrack.test/spam"></iframe>')
        accepted, refused = mm.split_players(content)
        self.assertEqual([r["service"] for r in accepted], ["mxdrop"])
        self.assertEqual([r["service"] for r in refused], ["adtrack.test"])

    def test_download_links_are_none_on_this_site(self):
        self.assertEqual(mm.find_download_links(CONTENT), [])

    def test_download_links_classify_bridges(self):
        content = ('<a href="https://mobilejsr.com/view/abc">v</a>'
                   '<a href="https://hubcloud.foo/d/xyz.mkv">f</a>'
                   '<a href="https://www.moviesmela.com/x/">internal</a>'
                   '<a href="https://bit.ly/promo">short</a>')
        rows = mm.find_download_links(content)
        self.assertEqual({r["service"]: r["status"] for r in rows},
                         {"mobilejsr.com": "blocked", "hubcloud.foo": "unverified"})
        self.assertTrue(all(r["playback_type"] == "download" for r in rows))


class TestParseTitle(unittest.TestCase):
    def test_air_date_tag_inside_a_paren(self):
        out = mm.parse_title("Bigg Boss (2026 Episode 102 [13-JAN]) Hindi Full Show")
        self.assertEqual(out["air_date_tag"], "13-JAN")
        self.assertEqual(out["year"], 2026)

    def test_air_date_tag_without_a_paren(self):
        out = mm.parse_title("Bigg Boss [13-JAN] Hindi Full Show")
        self.assertEqual(out["air_date_tag"], "13-JAN")
        self.assertIsNone(out["original_title"])


    def parse(self, title):
        return mm.parse_title(title)

    def test_movie_shape(self):
        out = self.parse("Haiwaan (2026) Hindi Full Movie Watch Online HD "
                         "Print Free Download")
        self.assertEqual(out["base_title"], "Haiwaan")
        self.assertEqual((out["year"], out["year_source"]), (2026, "title-paren"))
        self.assertEqual(out["languages"], ["Hindi"])
        self.assertEqual(out["quality"], "HD")
        self.assertEqual(out["quality_claim"], "HD Print")
        self.assertIsNone(out["episode"])

    def test_episode_inside_parens(self):
        out = self.parse("Bigg Boss (2026 Episode 51) Hindi Season 20 Watch Online HD "
                         "Print Free Download")
        self.assertEqual(out["base_title"], "Bigg Boss")
        self.assertEqual((out["season"], out["episode"]), (20, 51))
        self.assertFalse(out["complete_season"])

    def test_episode_range(self):
        out = self.parse("Undekhi (2026 Ep 7-8) Hindi Season 4 Watch Online HD "
                         "Print Free Download")
        self.assertEqual((out["episode"], out["episode_end"]), (7, 8))
        self.assertEqual(out["base_title"], "Undekhi")

    def test_numbering_outside_parens_with_air_date(self):
        out = self.parse("Bigg Boss (2021) Hindi Season 14 Episode 102 [13-JAN] "
                         "Watch Online HD Free Download")
        self.assertEqual(out["base_title"], "Bigg Boss")
        self.assertEqual((out["season"], out["episode"]), (14, 102))
        self.assertEqual(out["air_date_tag"], "13-JAN")

    def test_season_typo_is_recorded_not_hidden(self):
        out = self.parse("Duniya Ki Thain Thain (2026) Hindi Seaosn 1 Complete "
                         "Watch Online HD Print Free Download")
        self.assertEqual(out["season"], 1)
        self.assertEqual(out["season_source"], "title-token-typo")
        self.assertEqual(out["base_title"], "Duniya Ki Thain Thain")

    def test_final_season_does_not_leak_into_the_name(self):
        out = self.parse("The Marvelous Mrs. Maisel (2023 Ep 5) Hindi Dubbed Final "
                         "Season 5 Watch Online HD Print Free Download")
        self.assertEqual(out["base_title"], "The Marvelous Mrs. Maisel")

    def test_original_title_in_parens(self):
        out = self.parse("Samarbhumi (Vanmurai Paguthi 2021) Hindi Dubbed Full Movie "
                         "Watch Free Download")
        self.assertEqual(out["base_title"], "Samarbhumi")
        self.assertEqual(out["original_title"], "Vanmurai Paguthi")
        self.assertEqual(out["year"], 2021)

    def test_unofficial_dub_marker(self):
        out = self.parse("Extremity (2018) Unofficial Hindi Dubbed Full Movie "
                         "Watch Online HD Free Download")
        self.assertTrue(out["unofficial"])

    def test_year_outside_parens_falls_back_to_token(self):
        out = self.parse("Baaghi 2026 Hindi Full Movie Watch Online HD Free Download")
        self.assertEqual((out["year"], out["year_source"]), (2026, "title-token"))
        self.assertEqual(out["base_title"], "Baaghi")

    def test_number_that_belongs_to_the_work_stays(self):
        self.assertEqual(self.parse("3 Idiots (2009) Hindi Full Movie Watch Online "
                                    "HD Print Quality Free Download")["base_title"],
                         "3 Idiots")
        self.assertEqual(self.parse("Pehla Pyaar less than 1% chance (2024 EP 12) "
                                    "Hindi Season 1 Watch Online HD Free Download")
                         ["base_title"], "Pehla Pyaar less than 1% chance")

    def test_resolution_token_sets_quality(self):
        out = self.parse("Circuit Rider (2024) Hindi Dubbed Full Movie Watch "
                         "Online 1080p Free Download")
        self.assertEqual(out["resolution"], "1080p")
        self.assertEqual(out["quality"], "1080p")

    def test_dvd_claim_is_not_hd(self):
        out = self.parse("Waqt Hamara Hai (1993) Watch Full Movie Online DVD "
                         "Free Download")
        self.assertEqual(out["quality"], "DVD")

    def test_empty_and_title_only(self):
        self.assertEqual(self.parse("")["base_title"], "")
        self.assertEqual(self.parse(None)["raw_title"], "")
        self.assertEqual(self.parse("Inception")["base_title"], "Inception")

    def test_brand_is_scrubbed_from_display_name(self):
        self.assertEqual(self.parse("MoviesMela Present — Tiger (2024) Hindi Full "
                                    "Movie Watch Online HD Free Download")["base_title"],
                         "Present — Tiger")

    def test_release_labels(self):
        self.assertEqual(mm.release_label(self.parse("Haiwaan (2026) Hindi Full Movie "
                               "Watch Online HD Free Download"), "movie"),
                         "Watch Online")
        self.assertEqual(mm.release_label(self.parse("Lock Upp (2026 Ep 14) Hindi "
                               "Season 2 Watch Online HD Free Download"), "series"),
                         "Episode 14")
        self.assertEqual(mm.release_label(self.parse("Undekhi (2026 Ep 7-8) Hindi "
                               "Season 4 Watch Online HD Free Download"), "series"),
                         "Episodes 7-8")
        self.assertEqual(mm.release_label(self.parse("Anyaa (2025) Hindi Season 1 "
                               "Complete Watch Online HD Free Download"),
                               "complete_season"), "Season 1 Complete")
        self.assertEqual(mm.release_label({"season": None, "episode": None},
                               "complete_season"), "Season Complete")

    def test_media_type_rules(self):
        self.assertEqual(mm.media_type_for({"episode": 4, "season": 2,
                               "complete_season": False}, False), "series")
        self.assertEqual(mm.media_type_for({"episode": None, "season": 1,
                               "complete_season": False}, False), "complete_season")
        self.assertEqual(mm.media_type_for({"episode": None, "season": None,
                               "complete_season": False}, True), "complete_season")
        self.assertEqual(mm.media_type_for({"episode": None, "season": None,
                               "complete_season": False}, False), "movie")


class TestSynopsis(unittest.TestCase):
    def test_genuine_prose_is_kept(self):
        prose = ("<p>A lighthouse keeper on a windswept coast inherits a "
                 "journal that describes his own death three days in advance.</p>")
        self.assertEqual(mm.extract_synopsis(prose, "Beacon (2024) Hindi Full Movie",
                                             "Beacon"),
                         "A lighthouse keeper on a windswept coast inherits a "
                         "journal that describes his own death three days in "
                         "advance.")

    def test_prose_that_restarts_the_work_name_is_dropped(self):
        body = ("<p>A Samarbhumi is a 2026 Hindi web series about a family "
                "split by a property dispute, streamed straight from the "
                "platform you already know.</p>")
        self.assertIsNone(mm.extract_synopsis(body, "A Samarbhumi (2026)",
                                              "A Samarbhumi"))

    def test_short_and_ad_bodies_are_dropped(self):
        self.assertIsNone(mm.extract_synopsis("<p>short</p>", "X", "X"))
        self.assertIsNone(mm.extract_synopsis(
            "<p>Watch the full movie online in print quality free download "
            "from player 1 below.</p>", "X", "X"))


class TestTaxonomy(unittest.TestCase):
    def test_industry_and_year_categories(self):
        fields = mm.taxonomy_fields(["Hollywood Movies", "2024 Movies Hollywood"])
        self.assertEqual((fields["industry"], fields["country"]), ("Hollywood", "USA"))
        self.assertEqual(fields["year"], 2024)
        self.assertEqual(fields["genres"], [])

    def test_language_categories_set_audio(self):
        fields = mm.taxonomy_fields(["Hindi Dubbed Movies", "Urdu Dubbed Movies",
                                     "English Movies", "Watch Full Punjabi Movies Online"])
        self.assertEqual(fields["audio_languages"], ["Hindi", "Urdu", "English", "Punjabi"])

    def test_season_category_recognised_by_name_not_parent(self):
        fields = mm.taxonomy_fields(["Bigg Boss Season 20", "Indian Movies"])
        self.assertEqual(fields["season"], 20)
        self.assertEqual(fields["show_category"], "Bigg Boss Season 20")
        self.assertEqual(fields["genres"], ["Web Series"])

    def test_genre_categories(self):
        fields = mm.taxonomy_fields(["Horror Movies", "action movies", "Wrestling Videos"])
        self.assertEqual(sorted(fields["genres"]), ["Action", "Horror", "Wrestling"])

    def test_actor_categories_deduped_and_capitalised(self):
        fields = mm.taxonomy_fields(["Akshay Kumar Movies List", "sanjay dutt movies list",
                                     "Akshay Kumar Movies List"])
        self.assertEqual(fields["cast"], ["Akshay Kumar", "Sanjay Dutt"])

    def test_series_parents_and_noise(self):
        fields = mm.taxonomy_fields(["Shows / Series", "Seasons / WebSeries", "Articles",
                                     "Slot Oyna", "Tiger Shroff"])
        self.assertEqual(fields["genres"], ["Web Series"])
        self.assertEqual(fields["noise"], ["Articles", "Slot Oyna"])
        self.assertEqual(fields["unmapped"], ["Tiger Shroff"])

    def test_blank_name_is_skipped(self):
        self.assertEqual(mm.taxonomy_fields(["", "   "])["genres"], [])

    def test_unknown_category_stays_visible(self):
        fields = mm.taxonomy_fields(["Paranormal Movies"])
        self.assertEqual(fields["unmapped"], ["Paranormal Movies"])


class TestAdultFlag(unittest.TestCase):
    def test_explicit_token_flags(self):
        self.assertEqual(mm.looks_adult("Ratenight (2024) 18+ Hindi Dubbed Full Movie"), 1)
        self.assertEqual(mm.looks_adult("Erotic Thriller (2022) Hindi Full Movie"), 1)
        self.assertEqual(mm.looks_adult("Onlyfans Model (2025) Hindi Full Movie"), 1)

    def test_age_certification_flags(self):
        self.assertEqual(mm.looks_adult("Untitled (2024) A certified Hindi Full Movie"), 1)

    def test_ambiguous_alone_does_not_flag(self):
        self.assertEqual(mm.looks_adult("Sexy Samurai (2019) Hindi Dubbed Full Movie"), 0)

    def test_ambiguous_with_prose_flags(self):
        self.assertEqual(mm.looks_adult("Lust (2021) Hindi Short",
                                       prose=("An erotic film.",)), 1)

    def test_normal_drama_is_not_flagged(self):
        self.assertEqual(mm.looks_adult("Bigg Boss (2026 Episode 51) Hindi Season 20 "
                                       "Watch Online HD"), 0)

    def test_none_labels_are_tolerated(self):
        self.assertEqual(mm.looks_adult("x", None, ""), 0)


class TestBuildPost(unittest.TestCase):
    def test_movie_post(self):
        post = mm.build_post(wp_post(), TAXONOMY)
        self.assertEqual(post["canonical_key"], "haiwaan-2026")
        self.assertEqual(post["clean_title"], "Haiwaan")
        self.assertEqual(post["media_type"], "movie")
        self.assertEqual(post["year"], 2026)
        self.assertEqual(post["release_date"], "2026-10-28T00:21:20")
        self.assertEqual(post["industry"], "Bollywood")
        self.assertEqual(post["country"], "India")
        self.assertEqual(post["poster_url"],
                        "https://www.moviesmela.com/wp-content/uploads/2026/10/"
                        "Haiwaan-2026-Hindi.jpg")
        self.assertIsNone(post["synopsis"])
        self.assertEqual(len(post["releases"]), 1)
        self.assertEqual(len(post["releases"][0]["sources"]), 4)
        self.assertEqual(post["raw_meta"]["year_source"], "title-paren")
        self.assertEqual(post["raw_meta"]["players"],
                         [s["source_url"] for s in post["releases"][0]["sources"]])

    def test_episode_grouping_under_show(self):
        record = wp_post(
            slug="bigg-boss-2026-episode-51-hindi-season-20-watch-online",
            title={"rendered": "Bigg Boss (2026 Episode 51) Hindi Season 20 "
                               "Watch Online HD Print Free Download"},
            categories=[2582, 2583, 2])
        post = mm.build_post(record, TAXONOMY)
        self.assertEqual(post["canonical_key"], "bigg-boss")
        self.assertEqual(post["media_type"], "series")
        self.assertEqual(post["seasons"], "20")
        self.assertEqual(post["releases"][0]["episode_number"], 51)
        self.assertEqual(post["releases"][0]["season_number"], 20)
        self.assertEqual(post["genres"], "Web Series")

    def test_season_number_from_category_when_title_lacks_it(self):
        record = wp_post(title={"rendered": "Bigg Boss 51st Night Hindi Watch Online "
                                            "HD Free Download"},
                         categories=[2583])
        post = mm.build_post(record, TAXONOMY)
        self.assertEqual(post["releases"][0]["season_number"], 20)
        self.assertEqual(post["media_type"], "complete_season")

    def test_year_category_supplies_year_when_title_does_not(self):
        record = wp_post(title={"rendered": "Untitled Print Hindi Full Movie Watch "
                                            "Online HD Free Download"},
                         categories=[2582])
        post = mm.build_post(record, TAXONOMY)
        self.assertEqual(post["year"], 2026)
        self.assertEqual(post["raw_meta"]["year_source"], "year-category")

    def test_unknown_category_id_is_kept_verbatim(self):
        post = mm.build_post(wp_post(categories=[999999]), TAXONOMY)
        self.assertEqual(post["raw_meta"]["categories"], ["category:999999"])
        self.assertEqual(post["raw_meta"]["unmapped_categories"], ["category:999999"])

    def test_missing_taxonomy_map_still_builds(self):
        post = mm.build_post(wp_post(categories=[2582]), None)
        self.assertEqual(post["genres"], None)
        self.assertEqual(post["media_type"], "movie")

    def test_no_players_and_no_downloads_is_declined(self):
        record = wp_post(content={"rendered": "<p>Coming soon</p>"})
        self.assertIsNone(mm.build_post(record, TAXONOMY))

    def test_non_site_link_is_declined(self):
        self.assertIsNone(mm.build_post(wp_post(link="https://evil.test/x/"), TAXONOMY))

    def test_missing_slug_or_link_is_declined(self):
        self.assertIsNone(mm.build_post(wp_post(slug=""), TAXONOMY))
        self.assertIsNone(mm.build_post(wp_post(link=""), TAXONOMY))

    def test_title_without_a_name_falls_back_to_the_slug(self):
        record = wp_post(title={"rendered": "Watch Online HD Free Download"},
                         slug="some-odd-upload-2024")
        post = mm.build_post(record, TAXONOMY)
        self.assertEqual(post["clean_title"], "some odd upload")

    def test_unmappable_base_title_and_slug_is_declined(self):
        record = wp_post(title={"rendered": "HD HD"}, slug="   ")
        self.assertIsNone(mm.build_post(record, TAXONOMY))

    def test_refused_hosts_are_recorded_not_stored_as_sources(self):
        record = wp_post(content={"rendered":
                                  '<iframe src="https://mxdrop.to/e/a"></iframe>'
                                  '<iframe src="https://spamads.test/b"></iframe>'})
        post = mm.build_post(record, TAXONOMY)
        self.assertEqual([s["service"] for s in post["releases"][0]["sources"]],
                         ["mxdrop"])
        self.assertEqual(post["raw_meta"]["refused_hosts"], ["spamads.test"])

    def test_string_title_is_accepted(self):
        record = wp_post(title="Zidd (2024) Hindi Full Movie Watch Online HD "
                              "Free Download")
        self.assertEqual(mm.build_post(record, TAXONOMY)["clean_title"], "Zidd")

    def test_animated_category_sets_the_flag(self):
        record = wp_post(categories=[2509, 2582])
        self.assertEqual(mm.build_post(record, TAXONOMY)["is_animated"], 1)

    def test_subtitle_note_is_honest(self):
        post = mm.build_post(wp_post(), TAXONOMY)
        self.assertIsNone(post["raw_meta"]["subtitle_hint"])
        self.assertIn("no subtitle track URLs", post["raw_meta"]["subtitle_note"])

    def test_tag_ids_are_kept_without_inventing_names(self):
        self.assertEqual(mm.build_post(wp_post(tags=[62, 7]), TAXONOMY)
                         ["raw_meta"]["tag_ids"], [62, 7])

    def test_source_rows_are_unverified_and_local_without_a_probe(self):
        post = mm.build_post(wp_post(), TAXONOMY)
        resolved = mm.resolve_links(post)
        kinds = {source["playback_type"] for source in post["releases"][0]["sources"]}
        self.assertEqual(kinds, {"iframe", "url"})
        for source in post["releases"][0]["sources"]:
            self.assertEqual(source["status"], "unverified")
            self.assertNotIn("final_url", source)
        self.assertEqual(resolved["resolved"], {"probe": False, "deep": False})
        self.assertNotIn("mxdrop", resolved["raw_meta"])

    def test_the_embed_url_is_the_stored_identifier(self):
        post = mm.build_post(wp_post(), TAXONOMY)
        mxdrop = [s for s in post["releases"][0]["sources"] if s["service"] == "mxdrop"]
        self.assertEqual(len(mxdrop), 1)
        self.assertTrue(mxdrop[0]["source_url"].startswith("https://mxdrop."))
        self.assertNotIn(".mp4", mxdrop[0]["source_url"])
        self.assertIn(mxdrop[0]["source_url"], post["raw_meta"]["players"])

    def test_poster_without_a_usable_og_image_is_empty(self):
        self.assertEqual(mm.poster_from_post({"yoast_head_json": {"og_image": []}}), "")
        self.assertEqual(mm.poster_from_post({"yoast_head_json": {"og_image": "no"}}), "")
        self.assertEqual(mm.poster_from_post({}), "")

    def test_a_title_that_is_only_punctuation_is_declined(self):
        record = wp_post(title={"rendered": "Watch Online \u2026 Free Download"},
                         slug="\u2026")
        self.assertIsNone(mm.build_post(record, TAXONOMY))

    def test_slug_year_is_recorded_as_its_own_source(self):
        record = wp_post(title={"rendered": "Watch Online HD Free Download"},
                         slug="some-odd-upload-2024", categories=[2])
        post = mm.build_post(record, TAXONOMY)
        self.assertEqual((post["year"], post["raw_meta"]["year_source"]),
                         (2024, "slug-trailing-year"))
        self.assertEqual(post["clean_title"], "some odd upload")

    def test_playability_note_names_what_the_page_offers(self):
        note = mm.playability_note([{"service": "mxdrop", "playback_type": "url"},
                                    {"service": "do7go.com", "playback_type": "iframe"}])
        self.assertIn("resolves to a signed mp4", note)
        self.assertIn("do7go.com", note)
        all_iframes = mm.playability_note([{"service": "ok.ru", "playback_type": "iframe"}])
        self.assertIn("no WebView escape hatch", all_iframes)
        self.assertIn("no players", mm.playability_note([]))

    def test_classify_helper(self):
        self.assertEqual(mm.classify({"country": "Pakistan"}),
                         {"industry": "Lollywood", "country": "Pakistan"})
        self.assertEqual(mm.classify({"country": None, "industry": None}),
                         {"industry": None, "country": None})

    def test_sources_for_helper(self):
        self.assertEqual(mm.sources_for({"sources": [{"a": 1}]}), [{"a": 1}])
        self.assertEqual(mm.sources_for({}), [])


def mxdrop_verdict(**over) -> dict:
    """What host_resolvers.unwrap_mxdrop returns for the fixture's embed URL."""
    verdict = {"service": "mxdrop", "embed_url": "https://mxdrop.to/e/7kk0mpgdsmoqd4",
               "final_url": "https://n1sxu2vld.mxcontent.net/v2/x.mp4?s=a&e=1793165221",
               "is_temporary": True, "expires_in": 21600, "status": "active",
               "notes": [], "poster_url": "https://n1sxu2vld.mxcontent.net/thumbs/x.jpg",
               "signed_params": ["_t", "e", "s"], "vfile": "abc.mp4",
               "vserver": "n1sxu2vld", "subtitles": [], "http_status": 206,
               "size_bytes": 425208621, "content_type": "video/mp4"}
    verdict.update(over)
    return verdict


class TestProbeVerdicts(unittest.TestCase):
    def test_transport_failure_is_unknown(self):
        self.assertEqual(mm.verdict_from_probe(0, "", "", "OSError")["status"], "unknown")

    def test_redirect_reports_location(self):
        verdict = mm.verdict_from_probe(302, "", "https://mxdrop.top/e/x")
        self.assertEqual((verdict["status"], verdict["location"]),
                         ("redirect", "https://mxdrop.top/e/x"))

    def test_gate_codes_are_blocked(self):
        for code in (401, 403, 429):
            self.assertEqual(mm.verdict_from_probe(code, "", "")["status"], "blocked")

    def test_gate_page_on_403_is_js_required(self):
        verdict = mm.verdict_from_probe(403, "<h1>Verify You Are Human</h1>", "")
        self.assertEqual(verdict["status"], "js_required")

    def test_gone_is_dead(self):
        for code in (404, 410, 451):
            self.assertEqual(mm.verdict_from_probe(code, "", "")["status"], "dead")

    def test_server_error_and_no_content(self):
        self.assertEqual(mm.verdict_from_probe(503, "", "")["status"], "error")
        self.assertEqual(mm.verdict_from_probe(204, "", "")["status"], "blocked")
        self.assertEqual(mm.verdict_from_probe(418, "", "")["status"], "error")

    def test_player_page_is_active_but_not_a_stream(self):
        verdict = mm.verdict_from_probe(200, "<script>MDCore.init()</script>", "")
        self.assertEqual(verdict["status"], "active")
        self.assertEqual(verdict["media_urls"], [])

    def test_login_gate_without_player_is_js_required(self):
        verdict = mm.verdict_from_probe(200, "<a href='/user-login'>Log in</a>", "")
        self.assertEqual(verdict["status"], "js_required")

    def test_media_and_subtitle_urls_are_harvested(self):
        body = ('<script>player.load("https://cdn.mxdrop.top/hls/a.m3u8")'
                'tracks([{file:"https://cdn.mxdrop.top/subs/en.vtt"}])</script>')
        verdict = mm.verdict_from_probe(200, body, "")
        self.assertEqual(verdict["media_urls"], ["https://cdn.mxdrop.top/hls/a.m3u8"])
        self.assertEqual(verdict["subtitle_urls"],
                         ["https://cdn.mxdrop.top/subs/en.vtt"])
        self.assertEqual(verdict["status"], "active")

    def test_plain_200_with_nothing_is_unknown(self):
        self.assertEqual(mm.verdict_from_probe(200, "<p>hello</p>", "")["status"],
                         "unknown")

    def test_extract_urls_skips_trackers_and_dedupes(self):
        text = ('https://cdn.test/a.m3u8 https://cdn.test/a.m3u8 '
                'https://doubleclick.net/b.js //ok.ru/videoembed/1')
        urls = mm._extract_urls(text)
        self.assertEqual(urls, ["https://cdn.test/a.m3u8", "https://ok.ru/videoembed/1"])

    def test_probe_source_uses_the_seam(self):
        opener = fake_open([FakeResponse(b"MDCore", 200)])
        with mock.patch.object(mm, "_open", opener):
            verdict = mm.probe_source("https://pkembed.site/embed-x.html")
        self.assertEqual(verdict["status"], "active")

    def test_probe_source_transport_error_reaches_verdict(self):
        with mock.patch.object(mm, "http_get_once",
                               return_value=(0, "", "OSError: reset")):
            verdict = mm.probe_source("https://do7go.com/e/x")
        self.assertEqual(verdict["status"], "unknown")
        self.assertEqual(verdict["error"], "OSError: reset")

    def test_mxdrop_subtitles_are_recorded_and_never_invented(self):
        post = mm.build_post(wp_post(), TAXONOMY)
        quiet = {"status": "unknown", "location": "", "error": "",
                 "media_urls": [], "subtitle_urls": []}
        verdict = mxdrop_verdict(subtitles=[{"language": "English",
                                             "url": "https://h/en.vtt"}])
        with mock.patch.object(mm, "probe_source", return_value=quiet), \
                mock.patch.object(mm.host_resolvers, "unwrap_mxdrop",
                                  return_value=verdict), \
                mock.patch.object(mm, "_sleep"):
            resolved = mm.resolve_links(post, probe=True)
        self.assertEqual(resolved["raw_meta"]["mxdrop"][0]["subtitles"],
                         verdict["subtitles"])
        self.assertIn("English", resolved["raw_meta"]["subtitle_note"])
        self.assertNotIn("final_url", resolved["raw_meta"]["mxdrop"][0])

    def test_resolve_links_probe_path_sets_status_and_timestamp(self):
        post = mm.build_post(wp_post(), TAXONOMY)
        verdicts = [{"status": "active", "location": "https://mxdrop.top/e/x",
                     "error": "", "media_urls": ["https://cdn.mxdrop.top/a.m3u8"],
                     "subtitle_urls": ["https://cdn.mxdrop.top/en.vtt"]}]
        with mock.patch.object(mm, "probe_source", side_effect=verdicts * 3), \
                mock.patch.object(mm.host_resolvers, "unwrap_mxdrop",
                                  return_value=mxdrop_verdict()) as unpack:
            resolved = mm.resolve_links(post, probe=True, deep=True)
        sources = resolved["releases"][0]["sources"]
        self.assertEqual(sources[0]["status"], "active")
        self.assertEqual(sources[0]["final_url"], "https://mxdrop.top/e/x")
        self.assertTrue(sources[0]["last_checked"])
        self.assertEqual(resolved["raw_meta"]["probed_subtitle_urls"],
                         ["https://cdn.mxdrop.top/en.vtt"])
        self.assertEqual(resolved["discovered_subtitles"],
                         ["https://cdn.mxdrop.top/en.vtt"] * 3)
        self.assertEqual(unpack.call_count, 1)

    def test_resolve_links_ok_ru_gets_no_site_referer(self):
        seen = []

        def spy(url, referer=None):
            seen.append((url, referer))
            return {"status": "unknown", "location": "", "error": "",
                    "media_urls": [], "subtitle_urls": []}
        post = mm.build_post(wp_post(), TAXONOMY)
        with mock.patch.object(mm, "probe_source", side_effect=spy), \
                mock.patch.object(mm.host_resolvers, "unwrap_mxdrop",
                                  return_value=mxdrop_verdict()) as unpack:
            mm.resolve_links(post, probe=True)
        self.assertEqual(seen[0][1], None)
        self.assertEqual(seen[1][1], "https://www.moviesmela.com/")
        self.assertEqual(len(seen), 3)
        # the resolver is called with its defaults: no referer argument at all
        self.assertEqual(unpack.call_args.kwargs, {})

    def test_resolve_links_probe_error_string_is_stored(self):
        post = mm.build_post(wp_post(), TAXONOMY)
        verdict = {"status": "unknown", "location": "", "error": "OSError: reset",
                   "media_urls": [], "subtitle_urls": []}
        with mock.patch.object(mm, "probe_source", return_value=verdict), \
                mock.patch.object(mm.host_resolvers, "unwrap_mxdrop",
                                  return_value=mxdrop_verdict(status="blocked",
                                                              notes=["stale"])):
            resolved = mm.resolve_links(post, probe=True)
        self.assertEqual(resolved["releases"][0]["sources"][0]["probe_error"],
                         "OSError: reset")
        mxdrop = [s for s in resolved["releases"][0]["sources"]
                  if s["service"] == "mxdrop"]
        self.assertEqual(mxdrop[0]["status"], "blocked")
        self.assertEqual(resolved["raw_meta"]["mxdrop"][0]["notes"], ["stale"])

    def test_resolve_links_accepts_string_raw_meta(self):
        post = mm.build_post(wp_post(), TAXONOMY)
        post["raw_meta"] = "not a dict"
        verdict = {"status": "active", "location": "", "error": "",
                   "media_urls": ["https://cdn.test/a.m3u8"], "subtitle_urls": []}
        with mock.patch.object(mm, "probe_source", return_value=verdict), \
                mock.patch.object(mm.host_resolvers, "unwrap_mxdrop",
                                  return_value=mxdrop_verdict()):
            mm.resolve_links(post, probe=True)
        self.assertEqual(post["raw_meta"], "not a dict")


class TestStagingDatabase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "moviesmela.db"

    def tearDown(self):
        self.tmp.cleanup()

    def connect(self):
        conn = sqlite3.connect(self.db)
        conn.row_factory = sqlite3.Row
        return conn

    def test_schema_is_idempotent_and_complete(self):
        conn = self.connect()
        mm.ensure_schema(conn)
        mm.ensure_schema(conn)
        tables = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertLessEqual({"posts", "releases", "sources", "sitemap_cache"}, tables)
        columns = {r["name"] for r in conn.execute("PRAGMA table_info(posts)")}
        self.assertLessEqual(set(mm.POST_COLUMNS) | {"scraped_at"}, columns)
        conn.close()
        totals = mm.export_staging(self.db, [mm.build_post(wp_post(), TAXONOMY)])
        self.assertEqual(totals["posts_written"], 1)
        conn = self.connect()
        self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        conn.close()

    def test_migration_adds_missing_columns_with_types(self):
        conn = sqlite3.connect(self.db)
        conn.execute("CREATE TABLE posts (canonical_key TEXT PRIMARY KEY,"
                     " title TEXT NOT NULL, clean_title TEXT NOT NULL)")
        conn.execute("CREATE TABLE releases (id INTEGER PRIMARY KEY,"
                     " post_canonical_key TEXT)")
        conn.execute("CREATE TABLE sources (id INTEGER PRIMARY KEY, release_id INTEGER)")
        conn.execute("CREATE TABLE sitemap_cache (loc TEXT PRIMARY KEY)")
        conn.commit()
        conn.close()
        mm.ensure_schema(self.connect())
        conn = self.connect()
        info = {r["name"]: r["type"] for r in conn.execute("PRAGMA table_info(posts)")}
        self.assertEqual(info["is_18_plus"], "INTEGER")
        self.assertEqual(info["genres"], "TEXT")
        src = {r["name"]: r["type"] for r in conn.execute("PRAGMA table_info(sources)")}
        self.assertEqual(src["last_checked"], "INTEGER")
        conn.close()

    def test_export_replaces_only_its_own_page(self):
        post = mm.build_post(wp_post(), TAXONOMY)
        mm.export_staging(self.db, [post])
        other = mm.build_post(wp_post(
            slug="haiwaan-2026-hindi-full-movie-watch-online-dvd",
            link="https://www.moviesmela.com/haiwaan-2026-hindi-full-movie-"
                 "watch-online-dvd/"), TAXONOMY)
        mm.export_staging(self.db, [other])
        conn = self.connect()
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM releases").fetchone()[0], 2)
        # re-scraping the first page replaces that page's print, not the other
        mm.export_staging(self.db, [mm.build_post(wp_post(), TAXONOMY)])
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM releases").fetchone()[0], 2)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0], 8)
        conn.close()

    def test_raw_meta_accumulates_pages_per_work(self):
        mm.export_staging(self.db, [mm.build_post(wp_post(), TAXONOMY)])
        second = mm.build_post(wp_post(
            slug="haiwaan-2026-hindi-full-movie-watch-online-dvd",
            link="https://www.moviesmela.com/haiwaan-2026-hindi-full-movie-"
                 "watch-online-dvd/"), TAXONOMY)
        mm.export_staging(self.db, [second])
        conn = self.connect()
        meta = json.loads(conn.execute(
            "SELECT raw_meta FROM posts").fetchone()[0])
        self.assertEqual(meta["page_count"], 2)
        self.assertEqual(sorted(meta["pages"]),
                         sorted([LINK, second["url"]]))
        self.assertEqual(meta["site"], "moviesmela")
        conn.close()

    def test_corrupt_prior_raw_meta_does_not_break_merge(self):
        conn = self.connect()
        mm.ensure_schema(conn)
        conn.execute("INSERT INTO posts (canonical_key, title, clean_title, raw_meta)"
                     " VALUES ('haiwaan-2026','Haiwaan','Haiwaan','{not json')")
        conn.commit()
        conn.close()
        mm.export_staging(self.db, [mm.build_post(wp_post(), TAXONOMY)])
        conn = self.connect()
        self.assertEqual(json.loads(conn.execute(
            "SELECT raw_meta FROM posts").fetchone()[0])["page_count"], 1)
        conn.close()

    def test_export_skips_unusable_posts(self):
        totals = mm.export_staging(self.db, [
            None, {"clean_title": "x"}, {"clean_title": "x", "canonical_key": "x"},
            {"canonical_key": "k", "clean_title": "K", "releases": []},
        ])
        self.assertEqual(totals["skipped"], 4)
        self.assertEqual(totals["posts_written"], 0)

    def test_export_coerces_illegal_media_type(self):
        post = mm.build_post(wp_post(), TAXONOMY)
        post["media_type"] = "boxing tape"
        post["is_18_plus"] = None
        mm.export_staging(self.db, [post])
        conn = self.connect()
        row = conn.execute("SELECT media_type, is_18_plus, source_site FROM posts").fetchone()
        self.assertEqual((row["media_type"], row["is_18_plus"], row["source_site"]),
                         ("movie", 0, "moviesmela"))
        conn.close()

    def test_year_and_media_type_heal_across_writes(self):
        first = mm.build_post(wp_post(
            title={"rendered": "Untitled Hindi Full Movie Watch Online HD Free Download"},
            categories=[]), TAXONOMY)
        self.assertIsNone(first["year"])
        mm.export_staging(self.db, [first])
        second = mm.build_post(wp_post(categories=[2582]), TAXONOMY)
        second["canonical_key"] = first["canonical_key"]
        mm.export_staging(self.db, [second])
        conn = self.connect()
        row = conn.execute("SELECT year, media_type FROM posts").fetchone()
        self.assertEqual(row["year"], 2026)
        conn.close()

    def test_queue_row_is_marked_indexed(self):
        mm.export_staging(self.db, [mm.build_post(wp_post(), TAXONOMY)])
        conn = self.connect()
        row = conn.execute("SELECT scraped, slug, lastmod FROM sitemap_cache").fetchone()
        self.assertEqual((row["scraped"], row["slug"], row["lastmod"]),
                         (1, SLUG, "2026-10-28T00:21:20"))
        conn.close()

    def test_stats_report_iframes_apart_from_bytes(self):
        post = mm.build_post(wp_post(), TAXONOMY)
        mm.export_staging(self.db, [post])
        stats = mm.get_stats(self.db)
        self.assertEqual(stats["site"], "moviesmela")
        self.assertEqual(stats["sources"], 4)
        self.assertEqual(stats["iframe_rows"], 3)
        self.assertEqual(stats["resolvable_rows"], 1)
        self.assertEqual(stats["direct_byte_rows"], 0)
        self.assertEqual(stats["subtitle_rows"], 0)
        self.assertEqual(stats["download_rows"], 0)
        self.assertEqual(stats["source_status"], {"unverified": 4})
        self.assertEqual(stats["integrity"], "ok")
        self.assertEqual(stats["media_types"], {"movie": 1})
        self.assertEqual(stats["services"]["ok.ru"], 1)
        self.assertEqual(stats["with_year"], 1)
        self.assertEqual(stats["with_poster"], 1)
        self.assertEqual(stats["with_synopsis"], 0)
        self.assertEqual(stats["parked"], 0)
        self.assertEqual(stats["episodes"], 0)
        self.assertEqual(mm.stats(self.db)["posts"], 1)


class TestQueueAndCrawl(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "moviesmela.db"

    def tearDown(self):
        self.tmp.cleanup()

    def pages(self, *pages):
        """An `_open` stand-in answering one canned REST page per request."""
        bodies = [json.dumps(page).encode() for page in pages]
        return fake_open([FakeResponse(b, 200) for b in bodies])

    def test_load_taxonomy_pages_and_stops_on_short_page(self):
        opener = self.pages([{"id": 2, "name": "Indian Movies"},
                             {"id": 2582, "name": {"rendered": "2026 Movies"}}])
        with mock.patch.object(mm, "_open", opener):
            mapping = mm.load_taxonomy()
        self.assertEqual(mapping, {2: "Indian Movies", 2582: "2026 Movies"})

    def test_load_taxonomy_walks_to_the_next_full_page(self):
        first = [{"id": n, "name": f"cat {n}"} for n in range(100)]
        opener = self.pages(first, [{"id": 900, "name": "Last Category"}])
        with mock.patch.object(mm, "_open", opener):
            mapping = mm.load_taxonomy()
        self.assertEqual(len(mapping), 101)
        self.assertEqual(mapping[900], "Last Category")

    def test_cached_taxonomy_recreates_a_dropped_table(self):
        """ensure_schema owns the shape, so a queue file is never read blind."""
        opener = self.pages([{"id": 2, "name": "Indian Movies"}])
        with mock.patch.object(mm, "_open", opener):
            mm.load_taxonomy(self.db)
        conn = sqlite3.connect(self.db)
        conn.execute("DROP TABLE taxonomy_cache")
        conn.commit()
        conn.close()
        self.assertEqual(mm.cached_taxonomy(self.db), {})

    def test_load_taxonomy_caches_into_the_database(self):
        opener = self.pages([{"id": 2, "name": "Indian Movies"}])
        with mock.patch.object(mm, "_open", opener):
            mm.load_taxonomy(self.db)
        conn = sqlite3.connect(self.db)
        rows = conn.execute("SELECT id, name FROM taxonomy_cache").fetchall()
        conn.close()
        self.assertEqual(rows, [(2, "Indian Movies")])
        self.assertEqual(mm.cached_taxonomy(self.db), {2: "Indian Movies"})

    def test_cached_taxonomy_without_file_or_table(self):
        self.assertEqual(mm.cached_taxonomy(self.db), {})
        conn = sqlite3.connect(self.db)
        conn.close()
        self.assertEqual(mm.cached_taxonomy(self.db), {})

    def test_load_taxonomy_stops_on_bad_answer(self):
        with mock.patch.object(mm, "get_json", return_value=(403, None)):
            self.assertEqual(mm.load_taxonomy(), {})
        with mock.patch.object(mm, "get_json", return_value=(200, {"code": "rest_no_route"})):
            self.assertEqual(mm.load_taxonomy(), {})
        with mock.patch.object(mm, "get_json",
                               return_value=(200, [{"id": 5, "name": ""}])):
            self.assertEqual(mm.load_taxonomy(), {5: ""})

    def test_iter_catalog_posts_stops_on_every_anomaly(self):
        with mock.patch.object(mm, "get_json", return_value=(500, None)), silenced():
            self.assertEqual(list(mm.iter_catalog_posts()), [])
        with mock.patch.object(mm, "get_json", return_value=(200, {"a": 1})), silenced():
            self.assertEqual(list(mm.iter_catalog_posts()), [])
        with mock.patch.object(mm, "get_json", return_value=(200, None)), silenced():
            self.assertEqual(list(mm.iter_catalog_posts()), [])
        with mock.patch.object(mm, "get_json", return_value=(200, [])):
            self.assertEqual(list(mm.iter_catalog_posts()), [])

    def test_iter_catalog_posts_walks_full_pages(self):
        full = [wp_post(id=n) for n in range(mm.PAGE_SIZE)]
        opener = self.pages(full, [wp_post(id=99)])
        with mock.patch.object(mm, "_open", opener):
            posts = list(mm.iter_catalog_posts())
        self.assertEqual(len(posts), mm.PAGE_SIZE + 1)

    def test_iter_catalog_posts_honours_stop_flag(self):
        with mock.patch.object(mm, "STOP_REQUESTED", True):
            self.assertEqual(list(mm.iter_catalog_posts()), [])

    def test_sync_catalog_queues_with_the_record_attached(self):
        full = [wp_post(id=n, slug=f"movie-{n}",
                        link=f"https://www.moviesmela.com/movie-{n}/")
                for n in range(mm.PAGE_SIZE)]
        def route(url, timeout=60):
            if "categories" in url:
                return 200, json.dumps([{"id": 2, "name": "Indian Movies"}])
            if "page=1" in url:
                return 200, json.dumps(full)
            return 200, "[]"
        with mock.patch.object(mm, "http_get", side_effect=route), silenced():
            new = mm.sync_catalog(db_path=self.db)
        self.assertEqual(new, mm.PAGE_SIZE)
        conn = sqlite3.connect(self.db)
        rows = conn.execute("SELECT loc, scraped, raw_json FROM sitemap_cache").fetchall()
        conn.close()
        self.assertEqual(len(rows), mm.PAGE_SIZE)
        self.assertTrue(all(scraped == 0 for _, scraped, _ in rows))
        self.assertIn("content", json.loads(rows[0][2]))

    def test_sync_catalog_limit_and_dedupe_and_foreign_links(self):
        posts = [wp_post(id=1), wp_post(id=2, slug="dup", link=LINK),
                 wp_post(id=3, link="https://elsewhere.test/x/"),
                 wp_post(id=4, link=""),
                 wp_post(id=5, slug="movie-5", link="https://www.moviesmela.com/movie-5/"),
                 wp_post(id=6, slug="movie-6", link="https://www.moviesmela.com/movie-6/")]
        def route(url, timeout=60):
            if "categories" in url:
                return 200, json.dumps([{"id": 2, "name": "Indian Movies"}])
            return 200, json.dumps(posts)
        with mock.patch.object(mm, "http_get", side_effect=route), silenced():
            mm.sync_catalog(limit=2, db_path=self.db)
        conn = sqlite3.connect(self.db)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM sitemap_cache").fetchone()[0], 2)
        conn.close()

    def test_sync_catalog_requeues_parked_and_rechecks_edited(self):
        def route(url, timeout=60):
            if "categories" in url:
                return 200, json.dumps([{"id": 2, "name": "Indian Movies"}])
            return 200, json.dumps([wp_post(id=1), wp_post(id=2, slug="gone",
                                       link="https://www.moviesmela.com/gone/")])
        with mock.patch.object(mm, "http_get", side_effect=route), silenced():
            mm.sync_catalog(db_path=self.db)
        conn = sqlite3.connect(self.db)
        conn.execute("UPDATE sitemap_cache SET scraped = -1 WHERE slug = 'gone'")
        conn.execute("UPDATE sitemap_cache SET scraped = 1 WHERE slug = ?", (SLUG,))
        conn.commit()
        conn.close()
        # unchanged lastmod: stays indexed; parked row: queued again
        with mock.patch.object(mm, "http_get", side_effect=route), silenced():
            mm.sync_catalog(db_path=self.db)
        conn = sqlite3.connect(self.db)
        states = dict(conn.execute("SELECT slug, scraped FROM sitemap_cache").fetchall())
        conn.close()
        self.assertEqual(states[SLUG], 1)
        self.assertEqual(states["gone"], 0)
        # now the site reports the page as edited -> re-check
        def edited(url, timeout=60):
            if "categories" in url:
                return 200, json.dumps([{"id": 2, "name": "Indian Movies"}])
            return 200, json.dumps([wp_post(id=1, modified="2026-10-29T00:00:00")])
        with mock.patch.object(mm, "http_get", side_effect=edited), silenced():
            mm.sync_catalog(db_path=self.db)
        conn = sqlite3.connect(self.db)
        self.assertEqual(conn.execute(
            "SELECT scraped FROM sitemap_cache WHERE slug = ?", (SLUG,)).fetchone()[0], 2)
        conn.close()

    def test_sync_catalog_without_taxonomy_reports_once(self):
        with mock.patch.object(mm, "load_taxonomy", return_value={}), silenced() as buf:
            self.assertEqual(mm.sync_catalog(db_path=self.db), 0)
        self.assertIn("taxonomy unavailable", buf.getvalue())

    def test_sync_catalog_with_no_entries_says_so(self):
        def route(url, timeout=60):
            if "categories" in url:
                return 200, json.dumps([{"id": 2, "name": "Indian Movies"}])
            return 200, "[]"
        with mock.patch.object(mm, "http_get", side_effect=route), silenced() as buf:
            self.assertEqual(mm.sync_catalog(db_path=self.db), 0)
        self.assertIn("No catalog entries", buf.getvalue())

    def test_parse_record_prefers_the_embedded_record(self):
        post, verdict = mm._parse_record(
            LINK, json.dumps(wp_post()), SLUG, TAXONOMY)
        self.assertEqual(verdict, "ok")
        self.assertEqual(post["clean_title"], "Haiwaan")

    def test_parse_record_recovers_by_slug(self):
        with mock.patch.object(mm, "_fetch_post_by_slug",
                               return_value=wp_post()) as fetch:
            post, verdict = mm._parse_record(LINK, "{broken", SLUG, TAXONOMY)
        self.assertEqual(verdict, "ok")
        fetch.assert_called_once_with(SLUG)

    def test_parse_record_declines_a_gone_page(self):
        with mock.patch.object(mm, "_fetch_post_by_slug", return_value=None):
            self.assertEqual(mm._parse_record(LINK, None, SLUG, TAXONOMY),
                             (None, "not-a-post"))

    def test_parse_record_declines_a_page_without_players(self):
        record = wp_post(content={"rendered": "<p>trailer only</p>"})
        post, verdict = mm._parse_record(LINK, json.dumps(record), SLUG, TAXONOMY)
        self.assertIsNone(post)
        self.assertEqual(verdict, "no-players")

    def test_parse_record_keeps_the_queue_url_as_the_canonical_page(self):
        old = wp_post()
        old["link"] = "https://www.moviesmela.com/old-slug/"
        post, _ = mm._parse_record(LINK, json.dumps(old), SLUG, TAXONOMY)
        self.assertEqual(post["url"], LINK)

    def test_fetch_post_by_slug(self):
        with mock.patch.object(mm, "get_json", return_value=(200, [wp_post()])):
            self.assertEqual(mm._fetch_post_by_slug(SLUG)["id"], 439845)
        with mock.patch.object(mm, "get_json", return_value=(200, {"code": "no"})):
            self.assertIsNone(mm._fetch_post_by_slug(SLUG))
        with mock.patch.object(mm, "get_json", return_value=(200, [])):
            self.assertIsNone(mm._fetch_post_by_slug(""))

    def test_bump_error_records_and_parks_on_third_strike(self):
        mm.export_staging(self.db, [mm.build_post(wp_post(), TAXONOMY)])
        for _ in range(3):
            mm._bump_error(self.db, LINK, "http-error")
        conn = sqlite3.connect(self.db)
        row = conn.execute("SELECT scraped, error_count, raw_json FROM sitemap_cache").fetchone()
        conn.close()
        self.assertEqual((row[0], row[1]), (-1, 3))
        self.assertEqual(json.loads(row[2])["last_note"], "http-error")

    def test_bump_error_park_now_and_requeue(self):
        mm.export_staging(self.db, [mm.build_post(wp_post(), TAXONOMY)])
        mm._bump_error(self.db, LINK, "removed", park_now=True)
        conn = sqlite3.connect(self.db)
        self.assertEqual(conn.execute(
            "SELECT scraped FROM sitemap_cache").fetchone()[0], -1)
        conn.execute("UPDATE sitemap_cache SET scraped = 0, error_count = 0")
        conn.commit()
        conn.close()
        mm._bump_error(self.db, LINK, "no-players", requeue=True)
        conn = sqlite3.connect(self.db)
        self.assertEqual(conn.execute("SELECT scraped FROM sitemap_cache").fetchone()[0], 2)
        conn.close()

    def test_bump_error_edges(self):
        mm._bump_error(self.db, "", "no location")
        mm._bump_error(self.db, LINK, "row not in queue")
        conn = sqlite3.connect(self.db)
        conn.execute("INSERT INTO sitemap_cache (loc, raw_json) VALUES (?, 'garbage')",
                     (LINK,))
        conn.commit()
        conn.close()
        mm._bump_error(self.db, LINK, "note")
        conn = sqlite3.connect(self.db)
        self.assertEqual(json.loads(conn.execute(
            "SELECT raw_json FROM sitemap_cache").fetchone()[0])["last_note"], "note")
        conn.close()

    def seed(self, *records):
        conn = sqlite3.connect(self.db)
        mm.ensure_schema(conn)
        for index, record in enumerate(records):
            conn.execute(
                "INSERT INTO sitemap_cache (loc, slug, raw_json, scraped) "
                "VALUES (?, ?, ?, 0)",
                (record.get("link", LINK), record["slug"], json.dumps(record)))
        conn.execute("INSERT INTO taxonomy_cache (id, name, fetched_at) VALUES (2,"
                     " 'Indian Movies', 0)")
        conn.commit()
        conn.close()

    def test_crawl_pending_with_nothing_queued(self):
        with mock.patch.object(mm, "cached_taxonomy", return_value=TAXONOMY), silenced():
            totals = mm.crawl_pending(db_path=self.db, delay=0)
        self.assertEqual(totals["pages"], 0)

    def test_crawl_pending_parses_locally_with_no_socket(self):
        self.seed(wp_post())
        with mock.patch.object(mm, "_open",
                               side_effect=AssertionError("network in crawl")), \
                silenced() as buf:
            totals = mm.crawl_pending(db_path=self.db, workers=1, delay=0, verbose=True)
        self.assertEqual(totals["pages"], 1)
        self.assertEqual(totals["posts"], 1)
        self.assertEqual(totals["sources"], 4)
        self.assertIn("pending", buf.getvalue())
        stats = mm.get_stats(self.db)
        self.assertEqual(stats["sources"], 4)
        self.assertEqual(stats["iframe_rows"], 3)
        self.assertEqual(stats["resolvable_rows"], 1)

    def test_crawl_pending_batches_and_reports_progress(self):
        records = [wp_post(id=n, slug=f"m-{n}", link=f"https://www.moviesmela.com/m-{n}/")
                   for n in range(5)]
        self.seed(*records)
        with mock.patch.object(mm, "cached_taxonomy", return_value=TAXONOMY), \
                mock.patch.object(mm, "_sleep"), silenced():
            totals = mm.crawl_pending(db_path=self.db, workers=2, delay=0, batch_size=2)
        self.assertEqual(totals["pages"], 5)
        self.assertEqual(totals["posts"], 5)

    def test_crawl_pending_limit(self):
        self.seed(wp_post(), wp_post(id=2, slug="b", link="https://www.moviesmela.com/b/"))
        with mock.patch.object(mm, "cached_taxonomy", return_value=TAXONOMY), \
                mock.patch.object(mm, "_sleep"), silenced():
            totals = mm.crawl_pending(db_path=self.db, limit=1, workers=1, delay=0)
        self.assertEqual(totals["pages"], 1)

    def test_crawl_pending_declines_and_parks(self):
        self.seed(wp_post(content={"rendered": "<p>nothing here</p>"}))
        with mock.patch.object(mm, "cached_taxonomy", return_value=TAXONOMY), \
                mock.patch.object(mm, "_sleep"), silenced():
            totals = mm.crawl_pending(db_path=self.db, workers=1, delay=0)
        self.assertEqual(totals["not_indexable"], 1)
        conn = sqlite3.connect(self.db)
        self.assertEqual(conn.execute("SELECT scraped, error_count FROM sitemap_cache")
                         .fetchone(), (2, 1))
        conn.close()

    def test_crawl_pending_parks_a_gone_row(self):
        conn = sqlite3.connect(self.db)
        mm.ensure_schema(conn)
        conn.execute("INSERT INTO sitemap_cache (loc, slug, raw_json, scraped)"
                     " VALUES (?, 'gone', '{\"last_note\": \"x\"}', 0)",
                     ("https://www.moviesmela.com/gone/",))
        conn.commit()
        conn.close()
        with mock.patch.object(mm, "cached_taxonomy", return_value=TAXONOMY), \
                mock.patch.object(mm, "_fetch_post_by_slug", return_value=None), \
                mock.patch.object(mm, "_sleep"), silenced():
            totals = mm.crawl_pending(db_path=self.db, workers=1, delay=0)
        self.assertEqual(totals["not_indexable"], 1)
        conn = sqlite3.connect(self.db)
        self.assertEqual(conn.execute("SELECT scraped FROM sitemap_cache").fetchone()[0], -1)
        conn.close()

    def test_crawl_pending_counts_a_worker_exception_as_failed(self):
        self.seed(wp_post())
        with mock.patch.object(mm, "cached_taxonomy", return_value=TAXONOMY), \
                mock.patch.object(mm, "_parse_record", side_effect=RuntimeError("boom")), \
                mock.patch.object(mm, "_sleep"), silenced():
            totals = mm.crawl_pending(db_path=self.db, workers=1, delay=0)
        self.assertEqual(totals["failed"], 1)

    def test_crawl_pending_survives_a_dying_probe(self):
        self.seed(wp_post())
        with mock.patch.object(mm, "cached_taxonomy", return_value=TAXONOMY), \
                mock.patch.object(mm, "probe_source", side_effect=OSError("reset")), \
                mock.patch.object(mm.host_resolvers, "unwrap_mxdrop",
                                  side_effect=OSError("reset")), \
                mock.patch.object(mm, "_sleep"), silenced():
            totals = mm.crawl_pending(db_path=self.db, workers=1, delay=0, probe=True)
        self.assertEqual(totals["posts"], 1)
        conn = sqlite3.connect(self.db)
        raw = json.loads(conn.execute("SELECT raw_meta FROM posts").fetchone()[0])
        conn.close()
        self.assertEqual(raw["pages"][LINK]["post_id"], 439845)

    def test_crawl_pending_without_taxonomy_parks_everything(self):
        self.seed(wp_post())
        conn = sqlite3.connect(self.db)
        conn.execute("DELETE FROM taxonomy_cache")
        conn.commit()
        conn.close()
        with mock.patch.object(mm, "cached_taxonomy", return_value={}), \
                mock.patch.object(mm, "load_taxonomy", return_value={}), \
                mock.patch.object(mm, "_sleep"), silenced():
            totals = mm.crawl_pending(db_path=self.db, workers=1, delay=0)
        self.assertEqual(totals["not_indexable"], 1)

    def test_crawl_pending_drains_on_stop(self):
        self.seed(wp_post(), wp_post(id=2, slug="b",
                                     link="https://www.moviesmela.com/b/"))
        with mock.patch.object(mm, "STOP_REQUESTED", True), \
                mock.patch.object(mm, "cached_taxonomy", return_value=TAXONOMY), \
                silenced() as buf:
            totals = mm.crawl_pending(db_path=self.db, workers=1, delay=0)
        self.assertEqual(totals["pages"], 0)
        self.assertEqual(mm.get_stats(self.db)["posts"], 0)
        self.assertIn("2 pages pending", buf.getvalue())

    def test_crawl_pending_stops_mid_run(self):
        self.seed(*[wp_post(id=n, slug=f"m{n}",
                            link=f"https://www.moviesmela.com/m{n}/") for n in range(6)])
        state = {"n": 0}
        original = mm._parse_record

        def parse(*args, **kwargs):
            state["n"] += 1
            if state["n"] == 3:
                mm.STOP_REQUESTED = True
            return original(*args, **kwargs)
        try:
            with mock.patch.object(mm, "cached_taxonomy", return_value=TAXONOMY), \
                    mock.patch.object(mm, "_parse_record", side_effect=parse), \
                    mock.patch.object(mm, "_sleep"), silenced():
                mm.crawl_pending(db_path=self.db, workers=1, delay=0, batch_size=10)
        finally:
            mm.STOP_REQUESTED = False
        self.assertLess(state["n"], 6)

    def test_flush_empty_batch_is_a_no_op(self):
        totals = {"posts": 0, "releases": 0, "sources": 0, "not_indexable": 0}
        mm._flush(self.db, [], totals)
        self.assertEqual(totals["posts"], 0)


class TestParsePageAndCLI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "moviesmela.db"

    def tearDown(self):
        self.tmp.cleanup()

    def test_parse_page_fetches_one_post(self):
        with mock.patch.object(mm, "load_taxonomy", return_value=TAXONOMY), \
                mock.patch.object(mm, "_fetch_post_by_slug",
                                  return_value=wp_post()) as fetch:
            post = mm.parse_page(LINK)
        fetch.assert_called_once_with(SLUG)
        self.assertEqual(post["clean_title"], "Haiwaan")

    def test_parse_page_rejects_non_url_input(self):
        self.assertIsNone(mm.parse_page("not a url"))
        self.assertIsNone(mm.parse_page("https://www.moviesmela.com/"))

    def test_parse_page_when_the_post_is_gone(self):
        with mock.patch.object(mm, "load_taxonomy", return_value=TAXONOMY), \
                mock.patch.object(mm, "_fetch_post_by_slug", return_value=None):
            self.assertIsNone(mm.parse_page(LINK))

    def test_parser_choices(self):
        parser = mm._build_parser()
        self.assertEqual(parser.parse_args(["stats"]).command, "stats")
        self.assertEqual(parser.parse_args([]).command, "sync")
        self.assertTrue(parser.parse_args(["crawl", "--probe", "--deep"]).probe)

    def test_main_sync_and_crawl_and_stats(self):
        argv = ["--db", str(self.db), "--limit", "20", "--quiet"]
        with mock.patch.object(mm, "sync_catalog") as sync, \
                mock.patch.object(sys, "argv", ["import_moviesmela.py", "sync"] + argv):
            self.assertEqual(mm.main(), 0)
        sync.assert_called_once()
        with mock.patch.object(mm, "crawl_pending") as crawl, \
                mock.patch.object(sys, "argv", ["x", "crawl", "--db", str(self.db)]):
            self.assertEqual(mm.main(), 0)
        crawl.assert_called_once()
        mm.ensure_schema(sqlite3.connect(self.db))
        with silenced() as buf, mock.patch.object(
                sys, "argv", ["x", "stats", "--db", str(self.db)]):
            self.assertEqual(mm.main(), 0)
        self.assertIn("\"site\": \"moviesmela\"", buf.getvalue())

    def test_main_parse_and_resolve_print_the_post(self):
        with mock.patch.object(mm, "parse_page", return_value=mm.build_post(
                wp_post(), TAXONOMY)), mock.patch.object(mm, "resolve_links",
                side_effect=lambda p, probe=False, deep=False: p), silenced() as buf, \
                mock.patch.object(sys, "argv", ["x", "parse", "--url", LINK]):
            self.assertEqual(mm.main(), 0)
        self.assertIn("haiwaan-2026", buf.getvalue())
        with mock.patch.object(mm, "parse_page", return_value=mm.build_post(
                wp_post(), TAXONOMY)), mock.patch.object(mm, "probe_source",
                return_value={"status": "blocked", "location": "", "error": "",
                              "media_urls": [], "subtitle_urls": []}), \
                mock.patch.object(mm.host_resolvers, "unwrap_mxdrop",
                                  return_value=mxdrop_verdict()), \
                silenced(), mock.patch.object(sys, "argv",
                ["x", "resolve", "--url", LINK, "--deep"]):
            self.assertEqual(mm.main(), 0)

    def test_main_declines_a_non_catalog_page(self):
        with mock.patch.object(mm, "parse_page", return_value=None), silenced(), \
                mock.patch.object(sys, "argv", ["x", "parse", "--url", LINK]):
            self.assertEqual(mm.main(), 1)

    def test_main_requires_a_url_for_parse(self):
        with mock.patch.object(sys, "argv", ["x", "parse"]), self.assertRaises(SystemExit), \
                silenced():
            mm.main()

    def test_module_runs_as_main(self):
        """
        The `if __name__ == "__main__"` line itself.

        runpy re-executes the module in a fresh namespace, so mocks applied to the
        imported `mm` are invisible to it; the subcommand must therefore be one
        that touches nothing but the temporary database.
        """
        mm.export_staging(self.db, [])
        with mock.patch.object(sys, "argv",
                               ["import_moviesmela.py", "stats", "--db",
                                str(self.db)]), silenced():
            with self.assertRaises(SystemExit) as caught:
                runpy.run_module("import_moviesmela", run_name="__main__")
        self.assertEqual(caught.exception.code, 0)
        self.assertEqual(mm.cached_taxonomy(self.db), {})


class TestSignals(unittest.TestCase):
    def test_handlers_install_on_the_main_thread(self):
        self.assertTrue(mm._install_signal_handlers())

    def test_install_returns_false_off_the_main_thread(self):
        results = []

        def run():
            results.append(mm._install_signal_handlers())
        thread = threading.Thread(target=run)
        thread.start()
        thread.join()
        self.assertEqual(results, [False])

    def test_handler_sets_the_stop_flag_and_announces(self):
        previous = mm.STOP_REQUESTED
        try:
            with silenced() as buf:
                mm._signal_handler(signal.SIGINT, None)
            self.assertTrue(mm.STOP_REQUESTED)
            self.assertIn("draining", buf.getvalue())
        finally:
            mm.STOP_REQUESTED = previous
            mm._install_signal_handlers()


if __name__ == "__main__":
    with silenced() as output:
        unittest.main(verbosity=2, exit=False)
    sys.stdout.write(output.getvalue())
