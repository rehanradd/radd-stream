#!/usr/bin/env python3
"""
Fully offline tests for import_dramacool.py.

Run with:  python3 -S Fast_Fetch/importers/test_dramacool_import.py

Every fixture below is modelled on the live dramacool.li watch/series markup
captured while building the importer. No test may touch the network: syncs are
fed from a stubbed sitemap walk, probes are mocked, and resolve_links(probe=False)
is asserted to make zero calls.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import import_dramacool as dc  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

WATCH_URL = "https://dramacool.li/the-glory-fades-watch-full-episodes-eng-sub/"
SERIES_URL = "https://dramacool.li/series/the-glory-fades-2026/"
MOVIE_URL = "https://dramacool.li/the-adult-movie-watch-full-movie-eng-sub/"


def watch_html(title="The Glory Fades", year=2024, status="Completed",
               declared=3, current=3, synopsis="A quiet family drama.",
               type_label="Drama", genres=("Chinese Drama", "Mystery"),
               released="Jan 30, 2026 - Feb 9, 2026", current_class="",
               extra_body="", video=False):
    """The real watch-page shape: packaging <h1>, work <h2>, .spe grid."""
    genre_html = " ".join(f"<a>{g}</a>" for g in genres)
    current_mark = (f'<em class="epnow">{current_class or ""}</em>'
                    if current_class else "")
    video_html = ""
    if video:
        video_html = (
            '<video id="player"><source src="https://media.test-cdn.net/ep1-720p.m3u8"></video>'
            '<a href="https://media.test-cdn.net/ep1-720p.mp4">Download 720p</a>'
            '<a href="https://media.test-cdn.net/ep1-480p.mp4">Download 480p</a>'
        )
    return f"""<!doctype html>
<html><head>
<meta property="og:title" content="{title} ({year}) | Dramacool">
<meta property="og:image" content="https://img.test-cdn.net/poster.jpg">
<meta property="og:description" content="{synopsis}">
<meta name="keywords" content="dramacool, watch online">
<title>{title} ({year}) | Dramacool</title>
</head><body>
<div class="wrapper">
<h1 class="entry-title" itemprop="headline">{title} – Watch Full Episodes Eng Sub | Dramacool</h1>
<h2>{title} ({year})</h2>
<div class="details"><span class="alter">Fan Hua Luo Jin, 繁華落盡</span></div>
<div class="spe">
  <span><b>Status:</b> {status}</span>
  <span><b>Network:</b> <a href="https://dramacool.li/network/tencent-video/">Tencent Video</a></span>
  <span class="split"><b>Released:</b> {released}</span>
  <span><b>Duration:</b> 20 min.</span>
  <span><b>Country:</b> <a href="https://dramacool.li/country/china/">China</a></span>
  <span><b>Type:</b> {type_label}</span>
  <span><b>Episodes:</b> {declared}</span>
  <span class="split"><b>Casts:</b> <a href="https://dramacool.li/cast/jin-han/">Jin Han</a>, <a href="https://dramacool.li/cast/li-jia-nuo/">Li Jia Nuo</a></span>
</div>
<div class="genxed">{genre_html}</div>
<div class="desc mindes">{synopsis}<span class="colap"></span></div>
<div class="thumb"><img src="https://img.test-cdn.net/poster.jpg"></div>
<div class="episodelist"><span>Completed - {current_mark} / {declared}</span>
  <span>Eps {current}</span>
</div>
<div id="cs-player" data-post-id="6244683910894099581"></div>
{video_html}
{extra_body}
<script>
var tsMediaSelectedId = 3617;
var tsMediaEpNow = "{current}";
tsMedia(tsmmedia);
</script>
</div></body></html>"""


def series_html(title="The Glory Fades", year=2024):
    """The /series/ page shape: proper <h1>, a 'Synopsis ...' <h2> decoy."""
    return f"""<!doctype html><html><head>
<meta property="og:title" content="{title} ({year}) | Dramacool">
<meta property="og:image" content="https://img.test-cdn.net/series.jpg">
<title>{title} ({year}) | Dramacool</title></head><body>
<h1 class="entry-title" itemprop="name">{title} ({year})</h1>
<h2>Synopsis {title} ({year})</h2>
<h2>Watch {title} ({year})</h2>
<div class="spe">
  <span><b>Status:</b> Completed</span>
  <span><b>Country:</b> <a>China</a></span>
  <span><b>Type:</b> Drama</span>
  <span><b>Episodes:</b> 34</span>
</div>
<div class="genxed"><a>Chinese Drama</a></div>
<div class="desc mindes">Synopsis here.<span class="colap"></span></div>
<span>Eps 34</span>
<script src="https://dramacool.li/wp-content/konmijoyma/css.js"></script>
</body></html>"""


def movie_html(title="The Adult Movie", year=2023, genres=("Erotic",),
               synopsis="A forbidden affair."):
    return watch_html(title=title, year=year, status="Released", declared="",
                      current="", synopsis=synopsis, type_label="Movie",
                      genres=genres, released="Feb 1, 2026",
                      extra_body="").replace(
        f"{title} – Watch Full Episodes Eng Sub",
        f"{title} – Watch Full Movie Eng Sub")


SUBTITLE_BLOCK = """
<track kind="subtitles" src="/subs/ep1.en.vtt" srclang="en" label="English">
<a href="/subs/ep1.en.forced.vtt">English (Forced)</a>
<script type="application/json">
{"subtitles": {
  "en": "https://subs.test-cdn.net/ep1-en.srt",
  "ar": "https://subs.test-cdn.net/ep1-ar.vtt",
  "English": "https://subs.test-cdn.net/ep1-en-full.ass"
}}
</script>
<!-- #EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",NAME="Arabic",LANGUAGE="ar",URI="/subs/ep1-ar-hls.vtt" -->
"""


def subtitle_post():
    html = watch_html(extra_body=SUBTITLE_BLOCK)
    post = dc.parse_page(html, url=WATCH_URL)
    assert post is not None
    return post


def make_tmpdir(testcase):
    tmp = tempfile.TemporaryDirectory(prefix="dramacool_test_")
    testcase.addCleanup(tmp.cleanup)
    return Path(tmp.name)


# ---------------------------------------------------------------------------
# URL gate / provenance / identity
# ---------------------------------------------------------------------------

class UrlGateTests(unittest.TestCase):
    def test_unescape_then_quote_preserves_existing_escapes(self):
        raw = ("https://dramacool.li/สวัสดี-ตอน-1/?x=1&amp;y=2")
        quoted = dc._quote_url(raw)
        self.assertIn("%E0%B8%AA", quoted)
        self.assertNotIn("%25E0", quoted)          # no double encoding
        self.assertNotIn("&amp;", quoted)
        self.assertIn("&y=2", quoted)
        self.assertTrue(quoted.isascii())
        # A URL that is already escaped must pass through unchanged.
        already = "https://dramacool.li/%e0%b8%aa-watch/?a=1%20b"
        self.assertEqual(dc._quote_url(already), already)

    def test_http_get_quotes_unicode_before_request(self):
        seen = {}

        class FakeResponse:
            status = 200
            headers = {}
            def read(self):
                return b"ok"
            def geturl(self):
                return "https://dramacool.li/x"

        class FakeOpener:
            def open(self, url, timeout=30):
                seen["url"] = url
                return FakeResponse()

        with mock.patch.object(dc, "_OPENER", FakeOpener()):
            status, _final, body = dc.http_get("https://dramacool.li/เรื่อง/")
        self.assertEqual(status, 200)
        self.assertEqual(body, "ok")
        self.assertTrue(seen["url"].isascii())
        self.assertIn("%E0", seen["url"])


class TitleProvenanceTests(unittest.TestCase):
    def test_scrub_brand_and_packaging(self):
        self.assertEqual(dc.scrub_brand("Some Show | Dramacool"), "Some Show")
        self.assertEqual(
            dc.scrub_brand("Some Show – Watch Full Episodes Eng Sub"), "Some Show")
        parsed = dc.parse_title(
            "Some Show – Watch Full Episodes Eng Sub | Dramacool",
            "some-show-watch-full-episodes-eng-sub")
        self.assertEqual(parsed["clean_title"], "Some Show")
        self.assertNotIn("drama", parsed["clean_title"].lower())
        self.assertNotIn("watch full", parsed["clean_title"].lower())

    def test_parse_page_clean_title_has_no_brand_or_packaging(self):
        post = dc.parse_page(watch_html(), url=WATCH_URL)
        self.assertEqual(post["clean_title"], "The Glory Fades")
        self.assertEqual(post["title"], "The Glory Fades (2024)")
        for field in ("title", "clean_title"):
            lowered = post[field].lower()
            self.assertNotIn("dramacool", lowered)
            self.assertNotIn("watch full", lowered)
            self.assertNotIn("eng sub", lowered)
        self.assertEqual(post["source_site"], "dramacool")

    def test_series_page_prefers_proper_h1_over_synopsis_h2(self):
        post = dc.parse_page(series_html(), url=SERIES_URL)
        self.assertIsNotNone(post)
        self.assertEqual(post["clean_title"], "The Glory Fades")
        self.assertEqual(post["year"], 2024)
        self.assertEqual(post["content_type"], "complete_season")
        self.assertEqual(post["raw_meta"]["episodes_available"], 34)

    def test_canonical_key_is_title_derived_and_thai_titles_hash(self):
        a = dc.parse_page(watch_html(), url=WATCH_URL)
        b = dc.parse_page(watch_html(), url=SERIES_URL)
        self.assertEqual(a["canonical_key"], b["canonical_key"])
        self.assertEqual(a["canonical_key"], "the-glory-fades_2024")
        thai = dc.parse_title("สวัสดีปีใหม่ (2024)", "thai-slug")
        self.assertRegex(thai["canonical_key"], r"^drama-[0-9a-f]{12}_2024$")


class YearTests(unittest.TestCase):
    def test_year_comes_from_title_not_later_release_notice(self):
        # Released in 2026, but the work is a 2024 title: 2024 must win.
        post = dc.parse_page(watch_html(year=2024, released="Jan 30, 2026"), url=WATCH_URL)
        self.assertEqual(post["year"], 2024)
        self.assertEqual(post["canonical_key"], "the-glory-fades_2024")

    def test_year_falls_back_to_release_date_when_title_has_none(self):
        html = watch_html().replace("The Glory Fades (2024)",
                                    "The Glory Fades")
        post = dc.parse_page(html, url=WATCH_URL)
        self.assertEqual(post["year"], 2026)

    def test_season_number_extracted(self):
        parsed = dc.parse_title("Some Show Season 2 (2024)", "some-show-season-2")
        self.assertEqual(parsed["season_number"], 2)
        self.assertEqual(parsed["clean_title"], "Some Show")
        self.assertTrue(parsed["canonical_key"].endswith("_s02"))


class AdultFlagTests(unittest.TestCase):
    def test_labels_flag_adult_content(self):
        for label in ("18+", "XXX", "Erotic", "Hentai", "Adult Drama", "Pornstar"):
            self.assertTrue(dc.is_adult_content(label), label)
        self.assertTrue(dc.is_adult_content("Normal Show", "Erotic"))
        self.assertTrue(dc.is_adult_content("Show", "18+"))

    def test_ambiguous_prose_does_not_flag(self):
        self.assertFalse(dc.is_adult_content("Family Drama", prose=("adult themes",)))
        self.assertFalse(dc.is_adult_content("Family Drama", prose=("uncensored cut",)))
        self.assertTrue(dc.is_adult_content("Family Drama", prose=("explicit 18+ content",)))
        self.assertTrue(dc.is_adult_content("Family Drama", prose=("hentai adaptation",)))

    def test_parse_page_flags_18_plus_but_leaves_mainstream(self):
        adult = dc.parse_page(movie_html(), url=MOVIE_URL)
        self.assertEqual(adult["is_18_plus"], 1)
        self.assertEqual(adult["content_type"], "movie")

        mainstream = dc.parse_page(
            watch_html(synopsis="A story about adult themes and second chances."),
            url=WATCH_URL)
        self.assertEqual(mainstream["is_18_plus"], 0)


# ---------------------------------------------------------------------------
# Episodes / releases
# ---------------------------------------------------------------------------

class EpisodeTests(unittest.TestCase):
    def test_every_episode_gets_a_release_with_player_bridge(self):
        post = dc.parse_page(watch_html(current=3, declared=3), url=WATCH_URL)
        self.assertEqual(post["content_type"], "complete_season")
        self.assertEqual([r["episode_number"] for r in post["releases"]], [1, 2, 3])
        for rel in post["releases"]:
            self.assertEqual(len(rel["sources"]), 1)
            src = rel["sources"][0]
            self.assertEqual(src["playback_type"], "embed")
            self.assertEqual(src["service"], "csplayer")
            self.assertEqual(src["resource_id"], "6244683910894099581")
            self.assertEqual(src["status"], "unknown")
        seasons = json.loads(post["seasons"])
        self.assertEqual(len(seasons[0]["episodes"]), 3)

    def test_available_episode_signal_beats_declared_total(self):
        post = dc.parse_page(watch_html(current=5, declared=12), url=WATCH_URL)
        self.assertEqual(post["raw_meta"]["episodes_available"], 5)
        self.assertEqual(post["raw_meta"]["episodes_declared"], 12)
        self.assertEqual(len(post["releases"]), 5)

    def test_movie_is_one_movie_release_without_seasons(self):
        post = dc.parse_page(movie_html(), url=MOVIE_URL)
        self.assertEqual(post["content_type"], "movie")
        self.assertEqual(len(post["releases"]), 1)
        self.assertIsNone(post["releases"][0]["episode_number"])
        self.assertEqual(post["releases"][0]["label"], "Movie")
        self.assertIsNone(post["seasons"])

    def test_direct_media_playback_types_and_quality(self):
        post = dc.parse_page(watch_html(video=True, current=1, declared=1),
                             url=WATCH_URL)
        sources = post["releases"][0]["sources"]
        media = [s for s in sources if s["service"] == "direct"]
        types = {s["playback_type"] for s in media}
        self.assertIn("stream", types)
        self.assertIn("download", types)
        download_720 = [s for s in media if s["source_url"].endswith("ep1-720p.mp4")][0]
        self.assertEqual(download_720["quality"], "720p")
        self.assertEqual(download_720["is_temporary"], 0)
        stream = [s for s in media if s["source_url"].endswith(".m3u8")][0]
        self.assertEqual(stream["playback_type"], "stream")


# ---------------------------------------------------------------------------
# Subtitles
# ---------------------------------------------------------------------------

class SubtitleHarvestTests(unittest.TestCase):
    def test_all_tracks_are_harvested_including_duplicate_languages(self):
        post = subtitle_post()
        tracks = post["raw_meta"]["subtitles"]
        self.assertEqual(len(tracks), 6, [t["source_url"] for t in tracks])
        urls = [t["source_url"] for t in tracks]
        for expected in (
                "https://dramacool.li/subs/ep1.en.vtt",
                "https://dramacool.li/subs/ep1.en.forced.vtt",
                "https://subs.test-cdn.net/ep1-en.srt",
                "https://subs.test-cdn.net/ep1-ar.vtt",
                "https://subs.test-cdn.net/ep1-en-full.ass",
                "https://dramacool.li/subs/ep1-ar-hls.vtt"):
            self.assertIn(expected, urls)
        english = [t for t in tracks if t["language"] == "English"]
        arabic = [t for t in tracks if t["language"] == "Arabic"]
        self.assertEqual(len(english), 4)   # tag, forced anchor, JSON srt, JSON ass
        self.assertEqual(len(arabic), 2)    # JSON vtt + HLS media
        self.assertEqual(len({t["source_url"] for t in english}), 4)

    def test_each_track_becomes_its_own_subtitle_source_row(self):
        post = subtitle_post()
        ep1 = post["releases"][0]
        subtitle_sources = [s for s in ep1["sources"]
                            if s["playback_type"] == "subtitle"]
        self.assertEqual(len(subtitle_sources), 6)
        harvested = {t["source_url"] for t in post["raw_meta"]["subtitles"]}
        stored = {s["source_url"] for s in subtitle_sources}
        self.assertEqual(harvested, stored)
        for src in subtitle_sources:
            self.assertEqual(src["service"], "subtitle")
            self.assertEqual(src["status"], "unknown")
            self.assertEqual(src["is_temporary"], 0)
            self.assertTrue(src["source_name"].startswith("Subtitle: "))
            self.assertTrue(src["source_url"].startswith("https://"))
        # Other episodes still get their player bridge.
        self.assertEqual(len(post["releases"][1]["sources"]), 1)

    def test_player_config_placeholder_is_never_synthesised(self):
        config = dc._player_subtitle_config(
            'var csPlayerConfig = {"blogId":"x","subtitles":{"baseUrl":'
            '"https://sub.example.com","languages":{"English":"en","Arabic":"ar"}}};')
        self.assertFalse(config["usable"])
        self.assertIsNone(config["base_url"])
        self.assertEqual(config["declared_languages"]["English"], "en")
        self.assertEqual(config["declared_languages"]["Arabic"], "ar")

    def test_usable_player_config_yields_declared_languages(self):
        config = dc._player_subtitle_config(
            'var csPlayerConfig = {"subtitles":{"baseUrl":'
            '"https://subs.test-cdn.net/tracks/","languages":{"English":"en"}}};')
        self.assertTrue(config["usable"])
        self.assertEqual(config["base_url"], "https://subs.test-cdn.net/tracks/")

    def test_subtitle_rows_land_in_staging_database(self):
        tmp = make_tmpdir(self)
        db = tmp / "dramacool.db"
        post = subtitle_post()
        written = dc.export_staging(db, [post])
        self.assertEqual(written["subtitle_sources"], 6)
        self.assertEqual(written["sources_written"], 9)  # 3 embeds + 6 subtitles
        conn = sqlite3.connect(db)
        try:
            rows = conn.execute(
                "SELECT source_url, playback_type, status FROM sources"
                " WHERE playback_type = 'subtitle'").fetchall()
        finally:
            conn.close()
        self.assertEqual(len(rows), 6)
        self.assertTrue(all(status == "unknown" for _u, _t, status in rows))
        # raw_meta keeps the full track map.
        conn = sqlite3.connect(db)
        try:
            raw = conn.execute("SELECT raw_meta FROM posts").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(len(json.loads(raw)["subtitles"]), 6)


class HlsTests(unittest.TestCase):
    MASTER = """#EXTM3U
#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",NAME="English",LANGUAGE="en",DEFAULT=YES,URI="en/index.m3u8"
#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",NAME="Arabic",LANGUAGE="ar",URI="ar/index.m3u8"
#EXT-X-STREAM-INF:BANDWIDTH=6000000,RESOLUTION=1920x1080
1080/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=3000000,RESOLUTION=1280x720
720/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=1200000,RESOLUTION=854x480
480/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=600000,RESOLUTION=640x360
360/index.m3u8
"""

    def test_quality_tiers_and_subtitle_renditions(self):
        parsed = dc.parse_hls_master(
            self.MASTER, "https://media.test-cdn.net/show/master.m3u8")
        self.assertEqual([v["quality"] for v in parsed["variants"]],
                         ["1080p", "720p", "480p", "360p"])
        self.assertEqual(
            parsed["variants"][1]["url"],
            "https://media.test-cdn.net/show/720/index.m3u8")
        self.assertEqual([t["language"] for t in parsed["subtitles"]],
                         ["English", "Arabic"])
        self.assertTrue(parsed["subtitles"][0]["is_default"])

    def test_resolve_expands_active_hls_master_into_variants(self):
        post = dc.parse_page(watch_html(video=True, current=1, declared=1),
                             url=WATCH_URL)
        # Drop the mp4 downloads so only the m3u8 is probed.
        post["releases"][0]["sources"] = [
            s for s in post["releases"][0]["sources"]
            if s["source_url"].endswith(".m3u8")]

        def fake_probe(url, referer=None, timeout=20):
            return "active", self.MASTER

        with mock.patch.object(dc, "probe_source", side_effect=fake_probe):
            resolved = dc.resolve_links(post, probe=True)

        sources = resolved["releases"][0]["sources"]
        stream_qualities = {s["quality"] for s in sources
                            if s["playback_type"] == "stream"}
        self.assertEqual(stream_qualities, {"1080p", "720p", "480p", "360p"})
        subs = [s for s in sources if s["playback_type"] == "subtitle"]
        self.assertEqual(len(subs), 2)
        self.assertEqual({s["language"] for s in subs}, {"English", "Arabic"})
        self.assertEqual(len({s["source_url"] for s in subs}), 2)


# ---------------------------------------------------------------------------
# Link resolution: dead rows kept, probe=False never networks
# ---------------------------------------------------------------------------

class ResolveTests(unittest.TestCase):
    def _post_with_links(self):
        post = subtitle_post()
        post["releases"] = post["releases"][:1]
        post["releases"][0]["sources"] = [
            s for s in post["releases"][0]["sources"]
            if s["playback_type"] == "embed" or s["source_url"].endswith(".vtt")
        ][:3]
        return post

    def test_dead_links_are_retained_with_status(self):
        post = self._post_with_links()
        dead_url = next(s["source_url"] for s in post["releases"][0]["sources"]
                        if s["playback_type"] == "subtitle")

        def fake_probe(url, referer=None, timeout=20):
            if url == WATCH_URL:
                return "active", '<div id="cs-player"></div>'
            if url == dead_url:
                return "dead", "<html>410 Gone</html>"
            return "active", "WEBVTT"

        with mock.patch.object(dc, "probe_source", side_effect=fake_probe) as probe:
            resolved = dc.resolve_links(post, probe=True)

        sources = resolved["releases"][0]["sources"]
        self.assertEqual(len(sources), 3)                    # nothing dropped
        dead = [s for s in sources if s["source_url"] == dead_url]
        self.assertEqual(len(dead), 1)
        self.assertEqual(dead[0]["status"], "dead")
        self.assertIn("last_checked", dead[0])
        self.assertEqual(resolved["releases"][0]["sources"][0]["status"], "active")
        # Three distinct URLs, each probed exactly once.
        self.assertEqual(probe.call_count, 3)

    def test_embed_page_without_player_is_not_active(self):
        post = self._post_with_links()
        with mock.patch.object(dc, "probe_source", return_value=("active", "<html>login</html>")):
            resolved = dc.resolve_links(post, probe=True)
        embed = [s for s in resolved["releases"][0]["sources"]
                 if s["playback_type"] == "embed"][0]
        self.assertEqual(embed["status"], "error")

    def test_probe_false_makes_no_network_calls(self):
        post = self._post_with_links()
        before = json.dumps(post, sort_keys=True)
        with mock.patch.object(dc, "probe_source",
                               side_effect=AssertionError("probe_source called")) as probe, \
                mock.patch.object(dc, "http_get",
                                  side_effect=AssertionError("http_get called")) as get, \
                mock.patch.object(dc._OPENER, "open",
                                  side_effect=AssertionError("socket opened")) as opener:
            resolved = dc.resolve_links(post, probe=False)
        self.assertIs(resolved, post)
        self.assertEqual(json.dumps(post, sort_keys=True), before)
        self.assertEqual(probe.call_count, 0)
        self.assertEqual(get.call_count, 0)
        self.assertEqual(opener.call_count, 0)


# ---------------------------------------------------------------------------
# Sitemap sync / database safety / export
# ---------------------------------------------------------------------------

class SyncTests(unittest.TestCase):
    def test_only_watch_pages_are_queued(self):
        tmp = make_tmpdir(self)
        db = tmp / "dramacool.db"
        locs = [
            ("https://dramacool.li/", ""),
            ("https://dramacool.li/genres/chinese-drama/", ""),
            ("https://dramacool.li/series/the-glory-fades-2026/", ""),
            ("https://dramacool.li/?s=glory", ""),
            ("https://dramacool.li/the-glory-fades-watch-full-episodes-eng-sub/",
             "2026-10-25T00:00:00+00:00"),
            ("https://dramacool.li/a-movie-watch-full-movie-eng-sub/", ""),
        ]
        with mock.patch.object(dc, "_iter_sitemap_locs", return_value=iter(locs)):
            new = dc.sync_catalog(limit=None, db_path=db, verbose=False)
        self.assertEqual(new, 2)
        conn = sqlite3.connect(db)
        try:
            rows = conn.execute("SELECT loc, scraped FROM sitemap_cache ORDER BY loc").fetchall()
        finally:
            conn.close()
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(scraped == 0 for _loc, scraped in rows))
        self.assertTrue(all("watch-full-" in loc for loc, _s in rows))

    def test_sync_limit_and_idempotence(self):
        tmp = make_tmpdir(self)
        db = tmp / "dramacool.db"
        locs = [(f"https://dramacool.li/show-{i}-watch-full-episodes-eng-sub/", "")
                for i in range(5)]
        with mock.patch.object(dc, "_iter_sitemap_locs",
                               side_effect=lambda *a, **k: iter(locs)):
            self.assertEqual(dc.sync_catalog(limit=3, db_path=db, verbose=False), 3)
            self.assertEqual(dc.sync_catalog(limit=3, db_path=db, verbose=False), 0)
        conn = sqlite3.connect(db)
        try:
            count = conn.execute("SELECT COUNT(*) FROM sitemap_cache").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(count, 3)

    def test_db_guard_refuses_production_files(self):
        for name in ("fast_fetch.db", "merged_catalog_2026.db", "catalog_merged.db"):
            with self.assertRaises(ValueError):
                dc._guard_db_path(Path("/tmp") / name)
        self.assertEqual(dc._guard_db_path(Path("/tmp/dramacool.db")).name,
                         "dramacool.db")

    def test_export_is_idempotent_per_page(self):
        tmp = make_tmpdir(self)
        db = tmp / "dramacool.db"
        post = subtitle_post()
        first = dc.export_staging(db, [post])
        second = dc.export_staging(db, [post])
        self.assertEqual(first["posts_written"], 1)
        self.assertEqual(second["posts_written"], 1)
        stats = dc.get_stats(db)
        self.assertEqual(stats["posts"], 1)
        self.assertEqual(stats["releases"], 3)
        self.assertEqual(stats["sources"], 9)
        self.assertEqual(stats["subtitle_sources"], 6)
        self.assertEqual(stats["embed_sources"], 3)
        self.assertEqual(stats["indexed"], 1)
        self.assertEqual(stats["subtitle_languages"]["en"], 2)  # srt + ass
        self.assertEqual(stats["subtitle_languages"]["ar"], 2)  # json + hls

    def test_stats_on_fresh_database(self):
        tmp = make_tmpdir(self)
        stats = dc.get_stats(tmp / "dramacool.db")
        self.assertEqual(stats["posts"], 0)
        self.assertEqual(stats["sources"], 0)
        self.assertEqual(stats["subtitle_sources"], 0)


class PageVerdictTests(unittest.TestCase):
    def test_shelves_and_homepage_are_not_posts(self):
        self.assertIsNone(dc.parse_page("<html></html>", url="https://dramacool.li/"))
        self.assertIsNone(dc.parse_page(
            "<html></html>", url="https://dramacool.li/genres/chinese-drama/"))
        self.assertIsNone(dc.parse_page(
            "<html></html>", url="https://dramacool.li/?s=glory"))

    def test_removed_page_without_title(self):
        self.assertIsNone(dc.parse_page("<html><body>gone</body></html>", url=WATCH_URL))


if __name__ == "__main__":
    unittest.main(verbosity=2)
