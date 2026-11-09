#!/usr/bin/env python3
"""
test_megacartoons_import.py — offline unit tests for the MegaCartoons importer.

No test touches the network: every fetch/probe is a fake and every fixture
is shaped from pages measured live on this host on 2026-11-10 (the probe
run in the batch-1 checkpoint). The rules this suite keeps, and the measured
fact each one exists because of:

* wp-json works, but a post's ``content.rendered`` is synopsis only — the
  video is NOT there. The post page HTML carries the direct .mp4 twice
  (JW Player ``file:`` + JSON-LD ``contentUrl``) and the poster as
  ``og:image``. The importer fetches the page per post.
* posts carry a ``video-series`` taxonomy term id; the term name comes
  from ``/wp-json/wp/v2/video-series?include=<ids>``. One post per
  series, one release per episode, episode N = the post's date-ascending
  position inside its series (the site publishes no S/E numbers).
* the play gate is the legal-catalog gate: Range 206 + video/mp4 AND
  ffprobe (video + audio + duration > 0) -> ``active``. Range OK but
  ffprobe missing -> ``unverified``, never ``active``; a missing ffprobe
  binary fails closed the same way.
* cartoons are ``is_animated=1``; a post with no series term becomes its
  own one-episode series named by its title.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import import_megacartoons as mc  # noqa: E402

WP_POSTS = [
    {"id": 101, "slug": "woo-oo", "link": "https://www.megacartoons.net/woo-oo/",
     "title": {"rendered": "Woo-oo!"}, "date": "2024-12-17T20:52:00",
     "video-series": [123]},
    {"id": 102, "slug": "daytrip-of-doom",
     "link": "https://www.megacartoons.net/daytrip-of-doom/",
     "title": {"rendered": "Daytrip of Doom!"}, "date": "2024-12-18T20:52:00",
     "video-series": [123]},
    {"id": 103, "slug": "mad-love", "link": "https://www.megacartoons.net/mad-love/",
     "title": {"rendered": "Mad Love"}, "date": "2024-12-19T20:52:00",
     "video-series": [124]},
    {"id": 104, "slug": "lone-toon", "link": "https://www.megacartoons.net/lone-toon/",
     "title": {"rendered": "Lone Toon"}, "date": "2024-12-20T20:52:00",
     "video-series": []},
]

SERIES_TERMS = [
    {"id": 123, "slug": "ducktales", "name": "DuckTales"},
    {"id": 124, "slug": "batman-the-animated-series",
     "name": "Batman: The Animated Series"},
]

POST_HTML = """<!DOCTYPE html><html><head>
<meta property="og:image" content="https://www.megacartoons.net/wp-content/uploads/DuckTales-Woo-oo.jpg" />
<script type="application/ld+json">{"@context":"http://schema.org","@type":"VideoObject","name":"Woo-oo!","contentUrl":"https://ww.megacartoons.net/cartoons/ducktales/woo-oo.mp4"}</script>
</head><body>
<div id='jwppp-video-98301' class='jwplayer'>Loading the player...</div>
<script type='text/javascript'>
var playerInstance_98301 = jwplayer("jwppp-video-98301");
playerInstance_98301.setup({
file: "https://ww.megacartoons.net/cartoons/ducktales/woo-oo.mp4",
image: "https://www.megacartoons.net/wp-content/uploads/DuckTales-Woo-oo.jpg"
});
</script>
</body></html>"""

POST_HTML_NO_VIDEO = """<!DOCTYPE html><html><head>
<meta property="og:image" content="https://www.megacartoons.net/wp-content/uploads/x.jpg" />
</head><body><p>Donald Duck leaves his nephews.</p></body></html>"""


def range_ok(url):
    return {"ok": True, "status": 206, "content_type": "video/mp4"}


def range_fail(url):
    return {"ok": False, "status": 404, "content_type": ""}


def ffprobe_ok(url):
    return {"width": 640, "height": 480, "codec": "h264",
            "duration": 1320.0, "has_audio": True}


def ffprobe_none(url):
    return None


def enrich(posts, mp4="https://ww.megacartoons.net/cartoons/ducktales/woo-oo.mp4"):
    out = []
    for post in posts:
        copy = dict(post)
        copy["_mp4_url"] = mp4
        copy["_poster_url"] = ("https://www.megacartoons.net/wp-content/"
                               "uploads/DuckTales-Woo-oo.jpg")
        out.append(copy)
    return out


class TestParsePage(unittest.TestCase):
    def test_mp4_and_poster_from_jw_and_og_image(self):
        parsed = mc.parse_post_page(POST_HTML)
        self.assertEqual(parsed["mp4_url"],
                         "https://ww.megacartoons.net/cartoons/ducktales/woo-oo.mp4")
        self.assertEqual(parsed["poster_url"],
                         "https://www.megacartoons.net/wp-content/uploads/DuckTales-Woo-oo.jpg")

    def test_no_video_on_page(self):
        parsed = mc.parse_post_page(POST_HTML_NO_VIDEO)
        self.assertIsNone(parsed["mp4_url"])
        self.assertEqual(parsed["poster_url"],
                         "https://www.megacartoons.net/wp-content/uploads/x.jpg")


class TestSeriesNames(unittest.TestCase):
    def test_include_query_resolves_terms(self):
        seen = {}

        def fake_json(url):
            seen["url"] = url
            return SERIES_TERMS

        names = mc.fetch_series_names("https://www.megacartoons.net",
                                      [123, 124, 123], json_get=fake_json)
        self.assertIn("include=123,124", seen["url"])
        self.assertEqual(names[123], ("ducktales", "DuckTales"))
        self.assertEqual(names[124],
                         ("batman-the-animated-series",
                          "Batman: The Animated Series"))

    def test_json_failure_resolves_nothing(self):
        def boom(url):
            raise ValueError("no network in tests")

        self.assertEqual(mc.fetch_series_names(
            "https://www.megacartoons.net", [123], json_get=boom), {})


class TestBuildSeriesRecords(unittest.TestCase):
    def test_grouping_numbering_and_gate(self):
        records = mc.build_series_records(
            enrich(WP_POSTS), {123: ("ducktales", "DuckTales"),
                               124: ("batman-the-animated-series",
                                     "Batman: The Animated Series")},
            range_probe=range_ok, ffprobe_probe=ffprobe_ok)
        by_key = {r["canonical_key"]: r for r in records}
        self.assertEqual(sorted(by_key), [
            "megacartoons-batman-the-animated-series",
            "megacartoons-ducktales",
            "megacartoons-lone-toon",
        ])
        duck = by_key["megacartoons-ducktales"]
        self.assertEqual(duck["media_type"], "series")
        self.assertEqual(duck["is_animated"], 1)
        self.assertEqual(len(duck["releases"]), 2)
        self.assertEqual((duck["releases"][0]["episode"],
                          duck["releases"][1]["episode"]), (1, 2))
        # Date-ascending: Woo-oo! (Dec 17) is episode 1, Daytrip (Dec 18) is 2.
        self.assertEqual(duck["releases"][0]["raw_meta"]["wp_title"], "Woo-oo!")
        self.assertEqual(duck["releases"][1]["raw_meta"]["wp_title"],
                         "Daytrip of Doom!")
        src = duck["releases"][0]["sources"][0]
        self.assertEqual(src["status"], "active")
        self.assertEqual(src["playback_type"], "direct")
        self.assertEqual(src["mime_type"], "video/mp4")
        lone = by_key["megacartoons-lone-toon"]
        self.assertEqual(len(lone["releases"]), 1)
        self.assertEqual(lone["title"], "Lone Toon")

    def test_ffprobe_missing_is_unverified_not_active(self):
        records = mc.build_series_records(
            enrich(WP_POSTS[:1]), {123: ("ducktales", "DuckTales")},
            range_probe=range_ok, ffprobe_probe=ffprobe_none)
        self.assertEqual(records[0]["releases"][0]["sources"][0]["status"],
                         "unverified")

    def test_range_failure_is_unverified(self):
        records = mc.build_series_records(
            enrich(WP_POSTS[:1]), {123: ("ducktales", "DuckTales")},
            range_probe=range_fail, ffprobe_probe=ffprobe_ok)
        self.assertEqual(records[0]["releases"][0]["sources"][0]["status"],
                         "unverified")

    def test_no_ffprobe_flag_skips_the_second_gate(self):
        records = mc.build_series_records(
            enrich(WP_POSTS[:1]), {123: ("ducktales", "DuckTales")},
            range_probe=range_ok, ffprobe_probe=ffprobe_none,
            use_ffprobe=False)
        self.assertEqual(records[0]["releases"][0]["sources"][0]["status"],
                         "unverified")


class TestProbes(unittest.TestCase):
    def test_probe_ffprobe_needs_video_audio_duration(self):
        good = {"streams": [{"codec_type": "video", "codec_name": "h264",
                              "width": 640, "height": 480},
                             {"codec_type": "audio", "codec_name": "aac"}],
                "format": {"duration": "1320.0"}}

        class Proc:
            returncode = 0
            stdout = json.dumps(good)

        self.assertEqual(mc.probe_ffprobe("https://x/y.mp4",
                                          runner=lambda u: Proc())["width"], 640)
        no_audio = {"streams": [{"codec_type": "video", "codec_name": "h264",
                                  "width": 640, "height": 480}],
                    "format": {"duration": "1320.0"}}

        class Proc2:
            returncode = 0
            stdout = json.dumps(no_audio)

        self.assertIsNone(mc.probe_ffprobe("https://x/y.mp4",
                                           runner=lambda u: Proc2()))

    def test_probe_ffprobe_missing_binary_is_none(self):
        def missing(url):
            raise FileNotFoundError("no ffprobe")

        self.assertIsNone(mc.probe_ffprobe("https://x/y.mp4", runner=missing))


class TestExportAndSync(unittest.TestCase):
    def _tmp_db(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        return tmp.name

    def test_export_round_trip(self):
        db = self._tmp_db()
        records = mc.build_series_records(
            enrich(WP_POSTS), {123: ("ducktales", "DuckTales"),
                               124: ("batman-the-animated-series",
                                     "Batman: The Animated Series")},
            range_probe=range_ok, ffprobe_probe=ffprobe_ok)
        totals = mc.export_staging(db, posts=records)
        self.assertEqual((totals["posts_written"], totals["releases_written"],
                          totals["sources_written"]), (3, 4, 4))
        ok, result = mc.verify_db(db)
        self.assertTrue(ok)
        self.assertEqual(result["sources_active"], 4)
        conn = sqlite3.connect(db)
        row = conn.execute(
            "SELECT is_animated, source_site FROM posts "
            "WHERE canonical_key = 'megacartoons-ducktales'").fetchone()
        self.assertEqual(row, (1, "megacartoons"))
        conn.close()

    def test_sync_enumerates_wp_json_and_fetches_pages(self):
        db = self._tmp_db()

        def fake_json(url):
            if "video-series?include=" in url:
                return SERIES_TERMS
            if "page=1" in url:
                return WP_POSTS
            return []

        def fake_fetch(url):
            if "woo-oo" in url or "daytrip" in url or "mad-love" in url \
                    or "lone-toon" in url:
                return (200, POST_HTML)
            return (404, "")

        totals = mc.sync(db_path=db, limit=4, json_get=fake_json,
                         fetcher=fake_fetch, range_probe=range_ok,
                         ffprobe_probe=ffprobe_ok, delay=0)
        self.assertEqual(totals["posts_written"], 3)
        self.assertEqual(totals["releases_written"], 4)
        ok, result = mc.verify_db(db)
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
