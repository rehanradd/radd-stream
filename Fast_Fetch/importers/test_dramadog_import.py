#!/usr/bin/env python3
"""
test_dramadog_import.py — offline unit tests for the DramaDog importer.

No test touches the network: every fetch/probe is a fake and every fixture
is shaped from pages measured live on this host on 2026-11-10 (the probe
run in the batch-1 checkpoint). The rules this suite keeps, and the measured
fact each one exists because of:

* the sitemapindex holds 30 child sitemaps, one per platform, plus a
  static-pages sitemap that must be skipped — it carries no dramas.
* a drama page ships JSON-LD TVSeries with ``numberOfEpisodes`` (66 for
  the sample title) and ``data-ep`` buttons; the count comes from the
  JSON-LD first, data-ep max second.
* the .m3u8 pattern is ``v.dramadog.app/hls/<platform>/<id>/ep<N>.m3u8``:
  ep1/ep30/ep60 answer 206 with a real #EXTM3U, ep80 404s — the pattern
  holds exactly to the declared count and no further, so episode 1 and
  the last episode are probed per title and the middle episodes are
  stored active-by-pattern with raw_meta.pattern_derived set.
* a title whose ep1 does not probe is skipped entirely — a series with
  no playable first episode stages nothing.
* when the last episode 404s but data-ep says fewer, the count falls
  back to the data-ep max instead of staging episodes that do not exist.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import import_dramadog as dd  # noqa: E402

INDEX_XML = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<sitemap><loc>https://dramadog.app/sitemap-pages.xml</loc></sitemap>
<sitemap><loc>https://dramadog.app/sitemap-goodshort.xml</loc></sitemap>
<sitemap><loc>https://dramadog.app/sitemap-reelshort.xml</loc></sitemap>
</sitemapindex>"""

GOODSHORT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://dramadog.app/drama/after-divorce-my-three-brothers-spoil-me-rotten</loc></url>
<url><loc>https://dramadog.app/drama/reborn-to-freeze-them-all</loc></url>
<url><loc>https://dramadog.app/drama/her-vengeance</loc></url>
</urlset>"""

REELSHORT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://dramadog.app/drama/eight-years-no-longer-his</loc></url>
<url><loc>https://dramadog.app/drama/f-rank-tamer-s-rank-monster</loc></url>
</urlset>"""

DRAMA_HTML = """<!DOCTYPE html><html><head>
<title>After Divorce, My Three Brothers Spoil Me Rotten Full Episodes Free | DramaDog</title>
<script type="application/ld+json">{"@context":"https://schema.org","@type":"TVSeries","name":"After Divorce, My Three Brothers Spoil Me Rotten","url":"https://dramadog.app/drama/after-divorce-my-three-brothers-spoil-me-rotten","image":"https://dramadog.app/c/21758.webp","description":"Emily, the only heiress of the powerful Ashford family, elopes for love.","genre":["Secret Baby & Pregnancy","Revenge"],"numberOfEpisodes":66}</script>
</head><body>
<div class="episodes">
<button data-ep="1">Episode 1</button><button data-ep="2">Episode 2</button>
<button data-ep="65">Episode 65</button><button data-ep="66">Episode 66</button>
</div>
<video><source src="https://v.dramadog.app/hls/goodshort/31001925906/ep1.m3u8" type="application/x-mpegURL"></video>
<span>Episode <b>1</b> of 66</span>
</body></html>"""

DRAMA_HTML_NO_LD = """<!DOCTYPE html><html><head>
<title>Her Vengeance Full Episodes Free | DramaDog</title>
</head><body>
<button data-ep="1">Episode 1</button><button data-ep="2">Episode 2</button>
<button data-ep="3">Episode 3</button>
<video><source src="https://v.dramadog.app/hls/reelshort/777/ep1.m3u8"></video>
</body></html>"""

# Live 2026-11-10: blinkdrama/flickreels carry the drama SLUG as the stream
# id (…/hearts-under-fire/ep1.m3u8), not a number — and the slug form
# generalizes to epN (ep2/ep30 → 206, ep51 → 404 at 51 eps).
DRAMA_HTML_SLUG_ID = """<!DOCTYPE html><html><head>
<title>Hearts Under Fire Full Episodes Free | DramaDog</title>
<script type="application/ld+json">{"@context":"https://schema.org","@type":"TVSeries","name":"Hearts Under Fire","url":"https://dramadog.app/drama/hearts-under-fire","image":"https://dramadog.app/c/11223.webp","description":"A firefighter falls for the arson investigator.","genre":["Romance"],"numberOfEpisodes":51}</script>
</head><body>
<div class="episodes">
<button data-ep="1">Episode 1</button><button data-ep="51">Episode 51</button>
</div>
<video><source src="https://v.dramadog.app/hls/blinkdrama/hearts-under-fire/ep1.m3u8" type="application/x-mpegURL"></video>
</body></html>"""


def probe_ok(url):
    return {"ok": True, "status": 206, "is_playlist": True}


def probe_fail(url):
    return {"ok": False, "status": 404, "is_playlist": False}


def probe_upto(ep_max):
    def _probe(url):
        import re
        m = re.search(r"/ep(\d+)\.m3u8", url)
        n = int(m.group(1)) if m else 0
        if 1 <= n <= ep_max:
            return {"ok": True, "status": 206, "is_playlist": True}
        return {"ok": False, "status": 404, "is_playlist": False}
    return _probe


class TestSitemaps(unittest.TestCase):
    def test_index_lists_platform_sitemaps_and_skips_pages(self):
        children = dd.parse_sitemap_index(INDEX_XML)
        self.assertEqual(children, [
            "https://dramadog.app/sitemap-goodshort.xml",
            "https://dramadog.app/sitemap-reelshort.xml",
        ])

    def test_child_sitemap_yields_drama_urls(self):
        self.assertEqual(dd.parse_child_sitemap(GOODSHORT_XML), [
            "https://dramadog.app/drama/after-divorce-my-three-brothers-spoil-me-rotten",
            "https://dramadog.app/drama/reborn-to-freeze-them-all",
            "https://dramadog.app/drama/her-vengeance",
        ])

    def test_child_sitemap_ignores_non_drama_locs(self):
        xml = GOODSHORT_XML.replace(
            "https://dramadog.app/drama/her-vengeance",
            "https://dramadog.app/about")
        self.assertEqual(len(dd.parse_child_sitemap(xml)), 2)


class TestParsePage(unittest.TestCase):
    def test_json_ld_title_episodes_genres_poster(self):
        page = dd.parse_drama_page(
            DRAMA_HTML,
            "https://dramadog.app/drama/after-divorce-my-three-brothers-spoil-me-rotten")
        self.assertEqual(page["title"],
                         "After Divorce, My Three Brothers Spoil Me Rotten")
        self.assertEqual(page["episodes"], 66)
        self.assertEqual(page["max_data_ep"], 66)
        self.assertEqual(page["platform"], "goodshort")
        self.assertEqual(page["stream_id"], "31001925906")
        self.assertEqual(page["genres"], "Secret Baby & Pregnancy, Revenge")
        self.assertEqual(page["poster_url"], "https://dramadog.app/c/21758.webp")
        self.assertIn("Ashford family", page["synopsis"])
        self.assertEqual(page["is_18_plus"], 0)

    def test_no_json_ld_falls_back_to_title_and_data_ep(self):
        page = dd.parse_drama_page(
            DRAMA_HTML_NO_LD, "https://dramadog.app/drama/her-vengeance")
        self.assertEqual(page["title"], "Her Vengeance Full Episodes Free")
        self.assertEqual(page["episodes"], 3)
        self.assertEqual(page["platform"], "reelshort")
        self.assertEqual(page["stream_id"], "777")

    def test_non_drama_url_is_none(self):
        self.assertIsNone(dd.parse_drama_page(DRAMA_HTML, "https://dramadog.app/"))

    def test_episode_url_shape(self):
        self.assertEqual(
            dd.episode_url("goodshort", "31001925906", 30),
            "https://v.dramadog.app/hls/goodshort/31001925906/ep30.m3u8")

    def test_slug_stream_id_parses_and_generalizes(self):
        page = dd.parse_drama_page(
            DRAMA_HTML_SLUG_ID, "https://dramadog.app/drama/hearts-under-fire")
        self.assertEqual(page["platform"], "blinkdrama")
        self.assertEqual(page["stream_id"], "hearts-under-fire")
        self.assertEqual(page["episodes"], 51)
        record = dd.build_record(page, probe=probe_upto(51))
        self.assertEqual(len(record["releases"]), 51)
        self.assertEqual(record["releases"][29]["sources"][0]["final_url"],
                         "https://v.dramadog.app/hls/blinkdrama/hearts-under-fire/ep30.m3u8")


class TestBuildRecord(unittest.TestCase):
    def _page(self):
        return dd.parse_drama_page(
            DRAMA_HTML,
            "https://dramadog.app/drama/after-divorce-my-three-brothers-spoil-me-rotten")

    def test_sixty_six_releases_first_and_last_probed(self):
        record = dd.build_record(self._page(), probe=probe_upto(66))
        self.assertEqual(record["canonical_key"],
                         "dramadog-after-divorce-my-three-brothers-spoil-me-rotten")
        self.assertEqual(record["media_type"], "series")
        self.assertEqual(len(record["releases"]), 66)
        first = record["releases"][0]
        self.assertEqual((first["season"], first["episode"]), (1, 1))
        self.assertEqual(first["sources"][0]["final_url"],
                         "https://v.dramadog.app/hls/goodshort/31001925906/ep1.m3u8")
        self.assertEqual(first["sources"][0]["playback_type"], "direct")
        self.assertTrue(first["sources"][0]["raw_meta"]["probed"])
        middle = record["releases"][29]
        self.assertEqual(middle["episode"], 30)
        self.assertTrue(middle["sources"][0]["raw_meta"]["pattern_derived"])
        self.assertFalse(middle["sources"][0]["raw_meta"]["probed"])
        last = record["releases"][-1]
        self.assertEqual(last["episode"], 66)
        self.assertTrue(last["sources"][0]["raw_meta"]["probed"])

    def test_ep1_probe_failure_stages_nothing(self):
        self.assertIsNone(dd.build_record(self._page(), probe=probe_fail))

    def test_last_episode_404_falls_back_to_data_ep_max(self):
        # JSON-LD says 66 but the CDN only serves to 60; data-ep agrees.
        page = dd.parse_drama_page(DRAMA_HTML,
                                   "https://dramadog.app/drama/after-divorce-my-three-brothers-spoil-me-rotten")
        page["episodes"] = 66
        page["max_data_ep"] = 60
        record = dd.build_record(page, probe=probe_upto(60))
        self.assertEqual(len(record["releases"]), 60)

    def test_no_stream_on_page_stages_nothing(self):
        page = self._page()
        page["platform"] = None
        self.assertIsNone(dd.build_record(page, probe=probe_ok))


class TestExportAndSync(unittest.TestCase):
    def _tmp_db(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        return tmp.name

    def test_export_round_trip_and_re_export_replaces(self):
        db = self._tmp_db()
        page = dd.parse_drama_page(
            DRAMA_HTML,
            "https://dramadog.app/drama/after-divorce-my-three-brothers-spoil-me-rotten")
        record = dd.build_record(page, probe=probe_upto(66))
        totals = dd.export_staging(db, posts=[record])
        self.assertEqual((totals["posts_written"], totals["releases_written"],
                          totals["sources_written"]), (1, 66, 66))
        ok, result = dd.verify_db(db)
        self.assertTrue(ok)
        self.assertEqual(result["posts"], 1)
        # Re-export the same record: releases/sources replaced, not doubled.
        dd.export_staging(db, posts=[record])
        ok, result = dd.verify_db(db)
        self.assertTrue(ok)
        self.assertEqual((result["releases"], result["sources"]), (66, 66))
        conn = sqlite3.connect(db)
        row = conn.execute(
            "SELECT title, media_type, source_site FROM posts").fetchone()
        self.assertEqual(row, ("After Divorce, My Three Brothers Spoil Me Rotten",
                               "series", "dramadog"))
        conn.close()

    def test_sync_round_robins_platforms_and_respects_limit(self):
        db = self._tmp_db()
        pages = {
            "https://dramadog.app/sitemap.xml": (200, INDEX_XML),
            "https://dramadog.app/sitemap-goodshort.xml": (200, GOODSHORT_XML),
            "https://dramadog.app/sitemap-reelshort.xml": (200, REELSHORT_XML),
            "after-divorce": (200, DRAMA_HTML),
            "her-vengeance": (200, DRAMA_HTML_NO_LD),
        }

        def fake_fetch(url):
            for key, value in pages.items():
                if key in url:
                    return value
            return (200, DRAMA_HTML_NO_LD.replace("her-vengeance", "x")
                    .replace("reelshort/777", "reelshort/778"))

        totals = dd.sync(db_path=db, limit=3, fetcher=fake_fetch,
                         prober=probe_upto(66), delay=0)
        # Round-robin: goodshort #1, reelshort #1, goodshort #2 — not 3
        # from the first sitemap alone.
        self.assertEqual(totals["posts_written"], 3)
        conn = sqlite3.connect(db)
        slugs = [r[0] for r in conn.execute(
            "SELECT slug FROM posts ORDER BY slug")]
        self.assertEqual(slugs, ["after-divorce-my-three-brothers-spoil-me-rotten",
                                 "eight-years-no-longer-his",
                                 "reborn-to-freeze-them-all"])
        conn.close()

    def test_sync_with_no_drama_urls_writes_nothing(self):
        db = self._tmp_db()
        totals = dd.sync(db_path=db, limit=5,
                         fetcher=lambda url: (200, INDEX_XML.replace(
                             "sitemap-goodshort", "sitemap-empty")
                             .replace("sitemap-reelshort", "sitemap-empty2")),
                         prober=probe_ok, delay=0)
        self.assertEqual(totals["posts_written"], 0)


if __name__ == "__main__":
    unittest.main()
