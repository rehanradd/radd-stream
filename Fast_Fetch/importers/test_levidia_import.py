#!/usr/bin/env python3
"""
test_levidia_import.py — offline unit tests for the levidia staging importer.

Every network call is mocked or fed a saved-shape fixture; nothing here touches
levidia.ch. Run with:  python3 -S Fast_Fetch/importers/test_levidia_import.py
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

import import_levidia as lv  # noqa: E402

MOVIE_URL = "https://beta.levidia.ch/movie.php?watch=spiderman-brand-new-day"
EPISODE_URL = ("https://beta.levidia.ch/tv-episode.php?watch="
               "mobland-s2e1-i-wanna-be-your-dog")

MOVIE_FIXTURE = """<!DOCTYPE html><html><head>
<title>Watch Spider-Man: Brand New Day 2026 Online | PiratenZ </title>
<meta name="keywords" content="watch streaming download movie">
<link rel="canonical" href="https://beta.levidia.ch/movie.php?watch=spiderman-brand-new-day">
</head><body>
<div id="maincontent" style="width:735px;">
<h1><span class="onstat"><a href="https://beta.levidia.ch/movie.php?watch=spiderman-brand-new-day">Spider-Man: Brand New Day</a></span> <span class="ytitle">(<a href="/browse.php?nd=release&amp;year=2026">2026</a>)</span></h1>
<div class="plot">A forgotten Peter Parker lives alone as a full-time Spider-Man until mounting pressure triggers a dangerous change.</div>
<div class="kanan genre"><a href="https://beta.levidia.ch/browse.php?nd=genre&amp;id=21">Science Fiction</a> &middot; <a href="https://beta.levidia.ch/browse.php?nd=genre&amp;id=1">Action</a> &middot; <a href="https://beta.levidia.ch/browse.php?nd=genre&amp;id=2">Adventure</a></div>
<div class="pageheader"><div class="dnav"><ul class="nav"><li class="activelink"><a href="https://beta.levidia.ch/movie.php?watch=spiderman-brand-new-day">Everything</a></li></ul></div></div>
<ul class="mfeed">
<li class="xxx0"><span class="kiri thumb"><img src="/wtt.png" alt="wtt" class="lthumb"/></span><h2 class="mainlink kiri xxx2"><strong>Spider-Man: Brand New Day (2026)</strong> <span class="kanan xdt">spider </span></h2><span class="kiri xxx3">DVDRip </span><span class="kiri xxx1"><a href="https://beta.levidia.ch/video-hosts.php?h=15"><b>Wootly</b></a></span><span class="mainlink kiri"><a href="https://beta.levidia.ch/go.php?url=AAAA" class="xxx xflv">Play in Flash</a></span></li>
<li class="xxx0"><span class="kiri thumb"><img src="/wtd.png" alt="wtd" class="lthumb"/></span><h2 class="mainlink kiri xxx2"><strong>Spider-Man: Brand New Day (2026)</strong> <span class="kanan xdt">corintus </span></h2><span class="kiri xxx3">DVDrip </span><span class="kiri xxx1"><a href="https://beta.levidia.ch/video-hosts.php?h=66"><b>Luluvdo</b></a></span><span class="mainlink kiri"><a href="https://beta.levidia.ch/go.php?url=BBBB" class="xxx xflv">Play in Flash</a></span></li>
<li class="xxx0"><span class="kiri thumb"><img src="/wtd.png" alt="wtd" class="lthumb"/></span><h2 class="mainlink kiri xxx2"><strong>Spider-Man: Brand New Day (2026)</strong> <span class="kanan xdt">corintus </span></h2><span class="kiri xxx3">DVDrip </span><span class="kiri xxx1"><a href="https://beta.levidia.ch/video-hosts.php?h=65"><b>Dood.watch</b></a></span><span class="mainlink kiri"><a href="https://beta.levidia.ch/go.php?url=CCCC" class="xxx xflv">Play in Flash</a></span></li>
<li class="xxx0"><span class="kiri thumb"><img src="/wtd.png" alt="wtd" class="lthumb"/></span><h2 class="mainlink kiri xxx2"><strong>Spider-Man: Brand New Day (2026)</strong> <span class="kanan xdt">Fugitive </span></h2><span class="kiri xxx3">DVDrip </span><span class="kiri xxx1"><a href="https://beta.levidia.ch/video-hosts.php?h=66"><b>Luluvdo</b></a></span><span class="mainlink kiri"><a href="https://beta.levidia.ch/go.php?url=DDDD" class="xxx xflv">Play in Flash</a></span></li>
<li class="xxx0"><span class="kiri thumb"><img src="/wtt.png" alt="wtt" class="lthumb"/></span><h2 class="mainlink kiri xxx2"><strong>Spider-Man: Brand New Day (2026)</strong> <span class="kanan xdt">spider </span></h2><span class="kiri xxx3">DVDRip </span><span class="kiri xxx1"><a href="https://beta.levidia.ch/video-hosts.php?h=15"><b>Wootly</b></a></span><span class="mainlink kiri"><a href="https://beta.levidia.ch/go.php?url=AAAA" class="xxx xflv">Play in Flash</a></span></li>
</ul>
</div>
<div class="kiri msbar" style="width:190px;"><a href="https://beta.levidia.ch/movie.php?watch=spiderman-brand-new-day"><img src="https://md.goojara.to/10230777.jpg" class="mposter" alt="Watch Spider-Man" height="180" width="250"></a><div class="kiri minfo" style="width:180px;">
<div style="margin-top:10px;">Release: <a href="/browse.php?nd=release&amp;year=2026&amp;month=7">July 2026</a></div>
<div>Director: Destin Daniel Cretton </div>
<div>Language: en </div>
<div>Runtime: 145 Minutes </div>
<div>More Info: <a href="http://www.imdb.com/title/tt22084616" target="_blank" rel="nofollow">IMDb</a> </div>
<br /><div>Cast: <a href="/cast.php?name=Tom+Holland">Tom Holland</a>, <a href="/cast.php?name=Zendaya"> Zendaya</a>, <a href="/cast.php?name=Mark+Ruffalo"> Mark Ruffalo</a> </div>
<br /></div></div>
</body></html>"""

ADULT_FIXTURE = MOVIE_FIXTURE.replace(
    '<a href="https://beta.levidia.ch/browse.php?nd=genre&amp;id=2">Adventure</a>',
    '<a href="https://beta.levidia.ch/browse.php?nd=genre&amp;id=27">Adult</a>')

SUBTITLE_FIXTURE = MOVIE_FIXTURE.replace(
    "</body>",
    """<div class="subs">
<track kind="subtitles" src="/subs/spiderman-en.vtt" label="English" srclang="en">
<a href="https://beta.levidia.ch/subs/spiderman-es.srt">Spanish</a>
<a href="https://subs.example.net/spiderman-ar.ass">Arabic</a>
</div></body>""")

EPISODE_FIXTURE = """<!DOCTYPE html><html><head>
<title>Watch MobLand Season 2 Episode 1 Online | PiratenZ </title>
<link rel="canonical" href="https://beta.levidia.ch/tv-episode.php?watch=mobland-s2e1-i-wanna-be-your-dog">
</head><body>
<div id="maincontent" style="width:735px;">
<h1 class="onstat"><a href="https://beta.levidia.ch/tv-episode.php?watch=mobland-s2e1-i-wanna-be-your-dog">MobLand Season 2 Episode 1</a></h1>
<div class="plot instat"><b><a href="tv-show.php?watch=mobland">MobLand</a></b> &#8594; <b><a href="tv-show.php?watch=mobland&amp;s=2">Season 2</a></b> &#8594; <a href="https://beta.levidia.ch/tv-episode.php?watch=mobland-s2e1-i-wanna-be-your-dog"><b>Episode 1: I Wanna Be Your Dog </b></a></div>
<div class="plot" style="margin-top:5px;">Maeve and Conrad go to the dogs, leaving Harry to deal with the messy fallout.</div>
<div class="kanan genre"><span><a href="tv-episode.php?watch=mobland-s1e10-the-beast-in-me">&#8592; Previous Episode (S1 E10)</a></span>&nbsp; <a href="tv-show.php?watch=mobland">Full Episode List</a></div>
<ul class="mfeed">
<li class="xxx0"><span class="kiri thumb"><img src="/wtt.png" class="lthumb"/></span><h2 class="mainlink kiri xxx4"><b>MobLand Season 2 Episode 1</b> <span class="kanan xdt">spider </span></h2><span class="kiri xxx1 xx12"><b>Wootly</b> </span><span class="mainlink kanan"><a href="https://beta.levidia.ch/go.php?url=EEEE" class="xxx xflv">Play in Flash</a></span></li>
<li class="xxx0"><span class="kiri thumb"><img src="/wtd.png" class="lthumb"/></span><h2 class="mainlink kiri xxx4"><b>MobLand Season 2 Episode 1</b> <span class="kanan xdt">corintus </span></h2><span class="kiri xxx1 xx12"><b>Luluvdo</b> </span><span class="mainlink kanan"><a href="https://beta.levidia.ch/go.php?url=FFFF" class="xxx xflv">Play in Flash</a></span></li>
<li class="xxx0"><span class="kiri thumb"><img src="/wtd.png" class="lthumb"/></span><h2 class="mainlink kiri xxx4"><b>MobLand Season 2 Episode 1</b> <span class="kanan xdt">corintus </span></h2><span class="kiri xxx1 xx12"><b>Dood.watch</b> </span><span class="mainlink kanan"><a href="https://beta.levidia.ch/go.php?url=GGGG" class="xxx xflv">Play in Flash</a></span></li>
</ul>
</div>
<div class="kiri msbar"><a href="tv-episode.php?watch=mobland-s2e1-i-wanna-be-your-dog"><img src="https://md.goojara.to/20247061.jpg" class="mposter" alt="Watch I Wanna Be Your Dog"></a>
<div class="kiri minfo">
<div style="margin-top:10px;">Air Date: <a href="/browse.php?nd=release&amp;year=2026&amp;month=9">18 September 2026</a></div>
<div>Director: Stephan Pehrsson</div>
<div>Language: </div>
<div>Runtime: 50 Minutes</div>
<div>More Info: <a href="http://www.imdb.com/title/tt37427409">IMDb</a></div>
<br /><div>Cast: <a href="cast.php?name=Tom+Hardy">Tom Hardy</a>, <a href="cast.php?name=Pierce+Brosnan"> Pierce Brosnan</a></div>
</div></div>
</body></html>"""

TV_SHOW_FIXTURE = """<html><body><div id="maincontent"><h1 class="onstat">
<a href="tv-show.php?watch=mobland">MobLand</a></h1>
<div class="plot">Power is up for grabs.</div>
<ul class="mfeed"><li class="mlist links">Episode 01 - <b><a href="tv-episode.php?watch=mobland-s2e1-i-wanna-be-your-dog">I Wanna Be Your Dog</a></b></li></ul>
</div></body></html>"""

HOMEPAGE_FIXTURE = """<html><body><div id="maincontent">
<a href="https://beta.levidia.ch/movie.php?watch=the-uprising" title="The Uprising"><img src="https://md.goojara.to/1.jpg" class="promo"/></a>
<ul class="mfeed">
<li class="mlist pd5"><div class="mainlink"><a href="https://beta.levidia.ch/movie.php?watch=spiderman-brand-new-day"><strong>Spider-Man: Brand New Day</strong> (2026)</a></div></li>
<li class="mlist pd5"><div class="mainlink"><a href="https://beta.levidia.ch/tv-episode.php?watch=mobland-s2e1-i-wanna-be-your-dog"><strong>MobLand Season 2 Episode 1</strong></a></div></li>
<li class="mlist pd5"><div class="mainlink"><a href="https://beta.levidia.ch/tv-show.php?watch=mobland">MobLand</a></div></li>
<li class="mlist pd5"><div class="mainlink"><a href="https://beta.levidia.ch/browse.php?nd=genre&amp;id=1">Action</a></div></li>
</ul>
<a href="https://beta.levidia.ch/?tab=top&amp;v=all&amp;page=2">Next</a>
</div></body></html>"""

HOMEPAGE_PAGE2 = """<html><body><div id="maincontent"><ul class="mfeed">
<li class="mlist"><div class="mainlink"><a href="https://beta.levidia.ch/movie.php?watch=the-uprising">The Uprising (2026)</a></div></li>
<li class="mlist"><div class="mainlink"><a href="https://beta.levidia.ch/movie.php?watch=toy-story-5">Toy Story 5 (2026)</a></div></li>
</ul></div></body></html>"""


def parse_movie(body=MOVIE_FIXTURE):
    return lv.parse_page(body, MOVIE_URL)


def parse_episode():
    return lv.parse_page(EPISODE_FIXTURE, EPISODE_URL)


class TestUrlHandling(unittest.TestCase):
    def test_unescape_then_quote_with_the_catalog_safe_set(self):
        got = lv.prepare_url(" https://beta.levidia.ch/go.php?url=a+b&amp;x=1 ")
        self.assertEqual(got, "https://beta.levidia.ch/go.php?url=a+b&x=1")
        self.assertEqual(lv.prepare_url("https://x.test/a b.mp4"),
                         "https://x.test/a%20b.mp4")

    def test_host_membership_accepts_beta_and_apex_but_not_a_lookalike(self):
        self.assertTrue(lv._is_site_url("https://beta.levidia.ch/movie.php?watch=x"))
        self.assertTrue(lv._is_site_url("https://www.levidia.ch/levidia"))
        self.assertFalse(lv._is_site_url("https://levidia-copy.example.com/"))


class TestTitleCleaning(unittest.TestCase):
    def test_movie_seo_title_is_cleaned(self):
        got = lv.parse_title("Watch Spider-Man: Brand New Day 2026 Online | PiratenZ ",
                             "spiderman-brand-new-day")
        self.assertEqual(got["clean_title"], "Spider-Man: Brand New Day")
        self.assertEqual(got["year"], 2026)
        self.assertEqual(got["media_type"], "movie")
        self.assertEqual(got["canonical_key"], "spider-man-brand-new-day_2026")

    def test_episode_identity_groups_by_show_and_season(self):
        got = lv.parse_title("MobLand Season 2 Episode 1",
                             "mobland-s2e1-i-wanna-be-your-dog",
                             series_title="MobLand")
        self.assertEqual(got["clean_title"], "MobLand")
        self.assertEqual(got["season_number"], 2)
        self.assertEqual(got["episode_number"], 1)
        self.assertEqual(got["episode_title"], "I Wanna Be Your Dog")
        self.assertEqual(got["canonical_key"], "mobland_s02_e01")
        self.assertEqual(got["media_type"], "series")

    def test_year_named_work_keeps_its_name(self):
        got = lv.parse_title("1917 (2019)", "1917-2019")
        self.assertEqual(got["clean_title"], "1917")
        self.assertEqual(got["year"], 2019)

    def test_branding_is_scrubbed(self):
        for token in ("Levidia", "PiratenZ", "levidia.ch"):
            self.assertNotIn("levidia", lv.scrub_brand(token).lower())
            self.assertNotIn("piratenz", lv.scrub_brand(token).lower())

    def test_a_real_title_survives_the_scrubber(self):
        self.assertEqual(lv.scrub_brand("The Long Job"), "The Long Job")


class TestAdultFlagging(unittest.TestCase):
    def test_adult_genre_flags_the_row(self):
        self.assertTrue(lv.is_adult_content("Some Film", "Adult, Drama"))
        self.assertTrue(lv.is_adult_content("Title", "", "18+"))

    def test_mainstream_labels_are_not_flagged(self):
        self.assertFalse(lv.is_adult_content("Spider-Man: Brand New Day",
                                            "Science Fiction, Action"))
        self.assertFalse(lv.is_adult_content("MobLand", "Crime, Drama"))

    def test_ambiguous_prose_does_not_flag(self):
        blurb = "A sensual adult drama about lust and temptation."
        self.assertFalse(lv.is_adult_content("Dil Padosi", "Drama", prose=(blurb,)))


class TestHarvesting(unittest.TestCase):
    def test_host_rows_keep_every_label_and_dedupe_exact_links(self):
        rows = lv.harvest_hosts(MOVIE_FIXTURE)
        self.assertEqual(len(rows), 4)
        self.assertEqual([r["host"] for r in rows],
                         ["Wootly", "Luluvdo", "Dood.watch", "Luluvdo"])
        self.assertEqual([r["quality"] for r in rows],
                         ["DVDRip", "DVDrip", "DVDrip", "DVDrip"])
        self.assertEqual(rows[0]["token"], "AAAA")
        self.assertEqual(rows[0]["page_url"],
                         "https://beta.levidia.ch/go.php?url=AAAA")

    def test_episode_host_label_is_not_the_episode_title(self):
        rows = lv.harvest_hosts(EPISODE_FIXTURE)
        self.assertEqual([r["host"] for r in rows], ["Wootly", "Luluvdo", "Dood.watch"])
        self.assertTrue(all(r["quality"] is None for r in rows))

    def test_every_subtitle_language_becomes_its_own_track(self):
        tracks = lv.harvest_subtitles(SUBTITLE_FIXTURE, MOVIE_URL)
        self.assertEqual(len(tracks), 3)
        self.assertEqual([t["format"] for t in tracks], ["vtt", "srt", "ass"])
        self.assertEqual([t["label"] for t in tracks], ["English", "Spanish", "Arabic"])
        self.assertEqual(tracks[0]["url"],
                         "https://beta.levidia.ch/subs/spiderman-en.vtt")


class TestParsePage(unittest.TestCase):
    def test_movie_page_yields_a_staging_shaped_post(self):
        post = parse_movie()
        self.assertEqual(post["clean_title"], "Spider-Man: Brand New Day")
        self.assertEqual(post["year"], 2026)
        self.assertEqual(post["content_type"], "movie")
        self.assertEqual(post["source_site"], "levidia")
        self.assertEqual(post["is_18_plus"], 0)
        self.assertEqual(post["genres"], "Science Fiction, Action, Adventure")
        self.assertEqual(post["languages"], "English")
        self.assertEqual(post["poster_url"], "https://md.goojara.to/10230777.jpg")
        self.assertEqual(post["imdb_id"], "tt22084616")
        self.assertEqual(post["duration"], "145 Minutes")
        self.assertEqual(post["release_date"], "July 2026")
        self.assertEqual(post["director"], "Destin Daniel Cretton")
        self.assertIn("Tom Holland", post["cast_names"])

    def test_movie_releases_group_prints_and_keep_every_host(self):
        post = parse_movie()
        self.assertEqual(len(post["releases"]), 3)
        self.assertEqual(sum(len(r["sources"]) for r in post["releases"]), 4)
        self.assertEqual([r["label"] for r in post["releases"]],
                         ["DVDRip · spider", "DVDrip · corintus", "DVDrip · Fugitive"])
        sources = [s for r in post["releases"] for s in r["sources"]]
        self.assertTrue(all(s["status"] == "unknown" for s in sources))
        self.assertTrue(all(s["playback_type"] == "embed" for s in sources))

    def test_episode_page_groups_series_season_and_episode(self):
        post = parse_episode()
        self.assertEqual(post["clean_title"], "MobLand")
        self.assertEqual(post["content_type"], "series")
        self.assertEqual(post["season_number"], 2)
        self.assertEqual(post["episode_number"], 1)
        self.assertEqual(post["canonical_key"], "mobland_s02_e01")
        seasons = json.loads(post["seasons"])
        self.assertEqual(seasons[0]["season"], 2)
        self.assertEqual(seasons[0]["episodes"][0]["episode"], 1)
        self.assertEqual(seasons[0]["episodes"][0]["title"], "I Wanna Be Your Dog")
        self.assertEqual(post["release_date"], "18 September 2026")

    def test_subtitle_tracks_become_their_own_release_and_source_rows(self):
        post = parse_movie(SUBTITLE_FIXTURE)
        self.assertEqual(post["raw_meta"]["subtitle_tracks"][0]["language"], "en")
        sub = [r for r in post["releases"] if r["label"] == "Subtitles"]
        self.assertEqual(len(sub), 1)
        self.assertEqual(len(sub[0]["sources"]), 3)
        self.assertEqual({s["playback_type"] for s in sub[0]["sources"]}, {"subtitle"})
        self.assertEqual([s["service"] for s in sub[0]["sources"]],
                         ["subtitle", "subtitle", "subtitle"])
        self.assertEqual([s["source_name"] for s in sub[0]["sources"]],
                         ["English", "Spanish", "Arabic"])

    def test_adult_genre_sets_the_storage_flag(self):
        self.assertEqual(parse_movie(ADULT_FIXTURE)["is_18_plus"], 1)

    def test_an_episode_index_is_not_a_post(self):
        post, verdict = lv._parse_page(
            TV_SHOW_FIXTURE, "https://beta.levidia.ch/tv-show.php?watch=mobland")
        self.assertIsNone(post)
        self.assertEqual(verdict, "not-a-post")

    def test_a_shelf_url_is_not_a_post(self):
        self.assertIsNone(lv.parse_page(
            HOMEPAGE_FIXTURE, "https://beta.levidia.ch/levidia?v=movies"))

    def test_an_http_error_is_reported_for_the_queue(self):
        with mock.patch.object(lv, "http_get", return_value=(404, MOVIE_URL, "")):
            post, verdict = lv._parse_page(MOVIE_URL)
        self.assertIsNone(post)
        self.assertEqual(verdict, "http-error")


class TestResolveLinks(unittest.TestCase):
    def test_a_redirect_to_an_external_host_is_active_and_temporary(self):
        def chain(url, referer=None, timeout=25):
            return 302, "https://cdn2.example-stream.test/embed/abc?token=1", ""

        post = parse_movie()
        with mock.patch.object(lv, "http_get_once", side_effect=chain):
            lv.resolve_links(post, probe=True)
        src = post["releases"][0]["sources"][0]
        self.assertEqual(src["status"], "active")
        self.assertEqual(src["final_url"], "https://cdn2.example-stream.test/embed/abc?token=1")
        self.assertEqual(src["is_temporary"], 1)

    def test_a_404_is_recorded_as_dead_not_dropped(self):
        with mock.patch.object(lv, "http_get_once", return_value=(404, None, "")):
            post = lv.resolve_links(parse_movie(), probe=True)
        self.assertEqual(post["releases"][0]["sources"][0]["status"], "dead")
        self.assertEqual(sum(len(r["sources"]) for r in post["releases"]), 4)

    def test_a_bounce_to_the_site_is_blocked(self):
        def chain(url, referer=None, timeout=25):
            return 302, "https://beta.levidia.ch/", ""

        with mock.patch.object(lv, "http_get_once", side_effect=chain):
            post = lv.resolve_links(parse_movie(), probe=True)
        self.assertEqual(post["releases"][0]["sources"][0]["status"], "blocked")

    def test_a_js_gate_is_recorded_as_js_required(self):
        gate = "<html><head><title>Just a moment...</title></head><body>Enable JavaScript</body></html>"
        with mock.patch.object(lv, "http_get_once", return_value=(200, None, gate)):
            post = lv.resolve_links(parse_movie(), probe=True)
        self.assertEqual(post["releases"][0]["sources"][0]["status"], "js_required")

    def test_probe_off_leaves_the_bridge_unknown(self):
        post = lv.resolve_links(parse_movie(), probe=False)
        self.assertEqual(post["releases"][0]["sources"][0]["status"], "unknown")

    def test_subtitle_rows_are_never_probed(self):
        post = parse_movie(SUBTITLE_FIXTURE)
        with mock.patch.object(lv, "http_get_once", return_value=(404, None, "")) as probe:
            lv.resolve_links(post, probe=True)
        sub = [r for r in post["releases"] if r["label"] == "Subtitles"][0]
        self.assertEqual({s["status"] for s in sub["sources"]}, {"active"})
        self.assertEqual(probe.call_count, 4)  # only the four host rows

    def test_max_probes_caps_requests_and_leaves_the_rest_unknown(self):
        with mock.patch.object(lv, "http_get_once", return_value=(404, None, "")) as probe:
            post = lv.resolve_links(parse_movie(), probe=True, max_probes=2)
        self.assertEqual(probe.call_count, 2)
        statuses = [s["status"] for r in post["releases"] for s in r["sources"]]
        self.assertEqual(statuses.count("dead"), 2)
        self.assertEqual(statuses.count("unknown"), 2)


class TestStagingDatabase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = Path(self.tmp) / "levidia.db"
        self.post = parse_movie()

    def test_writes_only_the_isolated_staging_file(self):
        out = lv.export_staging(self.db, [self.post])
        self.assertEqual(out, {"posts_written": 1, "releases_written": 3,
                               "sources_written": 4, "skipped": 0})
        self.assertTrue(self.db.exists())

    def test_reimport_is_idempotent(self):
        lv.export_staging(self.db, [self.post])
        lv.export_staging(self.db, [self.post])
        conn = sqlite3.connect(self.db)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0], 1)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM releases").fetchone()[0], 3)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0], 4)
        conn.close()

    def test_episode_row_keeps_season_and_episode(self):
        post = parse_episode()
        lv.export_staging(self.db, [post])
        conn = sqlite3.connect(self.db)
        row = conn.execute("SELECT media_type, seasons FROM posts").fetchone()
        rel = conn.execute("SELECT season_number, episode_number FROM releases LIMIT 1").fetchone()
        conn.close()
        self.assertEqual(row[0], "series")
        self.assertEqual(json.loads(row[1])[0]["season"], 2)
        self.assertEqual(rel, (2, 1))

    def test_subtitle_sources_are_stored_as_their_own_rows(self):
        lv.export_staging(self.db, [parse_movie(SUBTITLE_FIXTURE)])
        conn = sqlite3.connect(self.db)
        rows = conn.execute(
            "SELECT source_name, playback_type FROM sources"
            " WHERE playback_type = 'subtitle' ORDER BY id").fetchall()
        conn.close()
        self.assertEqual(rows, [("English", "subtitle"), ("Spanish", "subtitle"),
                                ("Arabic", "subtitle")])

    def test_source_row_columns_are_the_ones_the_catalog_reads(self):
        lv.export_staging(self.db, [self.post])
        conn = sqlite3.connect(self.db)
        cols = {c[1] for c in conn.execute("PRAGMA table_info(sources)")}
        conn.close()
        for needed in ("source_name", "service", "resource_id", "source_url",
                       "final_url", "playback_type", "is_temporary", "status"):
            self.assertIn(needed, cols)

    def test_stats_and_get_stats_agree(self):
        lv.export_staging(self.db, [self.post, parse_episode()])
        st = lv.get_stats(self.db)
        self.assertEqual(st["posts"], 2)
        self.assertEqual(st["movies"], 1)
        self.assertEqual(st["series_episodes"], 1)
        self.assertEqual(st["releases"], 5)
        self.assertEqual(st["sources"], 7)
        self.assertEqual(st["subtitle_sources"], 0)
        self.assertEqual(st["source_status"], {"unknown": 7})
        self.assertEqual(lv.stats(self.db), st)

    def test_no_provenance_token_reaches_a_display_column(self):
        lv.export_staging(self.db, [self.post])
        conn = sqlite3.connect(self.db)
        row = conn.execute("SELECT title, clean_title, synopsis, genres FROM posts").fetchone()
        conn.close()
        joined = " ".join(str(v) for v in row).lower()
        for needle in ("levidia", "piratenz", "go.php", "wootly", "luluvdo"):
            self.assertNotIn(needle, joined)


class TestSyncCatalog(unittest.TestCase):
    def test_no_sitemap_falls_back_to_homepage_pagination(self):
        tmp = Path(tempfile.mkdtemp()) / "levidia.db"

        def get(url, timeout=30, retries=3):
            if url.endswith("/sitemap.xml"):
                return 404, url, ""
            if "page=2" in url:
                return 200, url, HOMEPAGE_PAGE2
            return 200, url, HOMEPAGE_FIXTURE

        with mock.patch.object(lv, "http_get", side_effect=get):
            added = lv.sync_catalog(db_path=tmp, max_pages=2)
        self.assertEqual(added, 4)
        conn = sqlite3.connect(tmp)
        locs = [r[0] for r in conn.execute("SELECT loc FROM sitemap_cache").fetchall()]
        conn.close()
        self.assertTrue(all(("/movie.php?watch=" in l or "/tv-episode.php?watch=" in l)
                            for l in locs))
        self.assertNotIn("https://beta.levidia.ch/tv-show.php?watch=mobland", locs)
        self.assertNotIn("https://beta.levidia.ch/browse.php?nd=genre&id=1", locs)

    def test_limit_stops_before_the_next_listing_page(self):
        tmp = Path(tempfile.mkdtemp()) / "levidia.db"
        calls = []

        def get(url, timeout=30, retries=3):
            calls.append(url)
            if url.endswith("/sitemap.xml"):
                return 404, url, ""
            return 200, url, HOMEPAGE_FIXTURE

        with mock.patch.object(lv, "http_get", side_effect=get):
            added = lv.sync_catalog(limit=2, db_path=tmp, max_pages=3)
        self.assertEqual(added, 2)
        self.assertFalse(any("page=" in c for c in calls))

    def test_a_sitemap_when_one_exists_is_preferred(self):
        tmp = Path(tempfile.mkdtemp()) / "levidia.db"
        urlset = ('<urlset><url><loc>https://beta.levidia.ch/movie.php?watch=the-uprising'
                  '</loc></url><url><loc>https://beta.levidia.ch/tv-episode.php?watch='
                  'mobland-s2e1-i-wanna-be-your-dog</loc></url><url><loc>https://'
                  'beta.levidia.ch/tv-show.php?watch=mobland</loc></url></urlset>')
        with mock.patch.object(lv, "http_get", return_value=(200, lv.SITEMAP_URL, urlset)):
            added = lv.sync_catalog(db_path=tmp)
        self.assertEqual(added, 2)

    def test_resync_does_not_reset_indexed_pages(self):
        tmp = Path(tempfile.mkdtemp()) / "levidia.db"

        def get(url, timeout=30, retries=3):
            if url.endswith("/sitemap.xml"):
                return 404, url, ""
            return 200, url, HOMEPAGE_FIXTURE

        with mock.patch.object(lv, "http_get", side_effect=get):
            lv.sync_catalog(limit=2, db_path=tmp)
        conn = sqlite3.connect(tmp)
        conn.execute("UPDATE sitemap_cache SET scraped = 1")
        conn.commit()
        conn.close()
        with mock.patch.object(lv, "http_get", side_effect=get):
            self.assertEqual(lv.sync_catalog(limit=2, db_path=tmp), 0)


class TestMergeCatalogsContract(unittest.TestCase):
    """merge_catalogs.py must be able to read this staging shape."""

    def test_source_family_is_staging(self):
        tmp = Path(tempfile.mkdtemp()) / "levidia.db"
        lv.export_staging(tmp, [parse_movie()])
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        import merge_catalogs
        conn = sqlite3.connect(tmp)
        conn.row_factory = sqlite3.Row
        self.assertEqual(merge_catalogs._source_family(conn), "staging")
        conn.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
