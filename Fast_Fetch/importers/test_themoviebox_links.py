#!/usr/bin/env python3
"""
test_themoviebox_links.py — the rendition/mirror rules of the themoviebox importer.

Offline only: every payload is the hydrated ``__NUXT_DATA__`` shape the site
ships, encoded with the same devalue pool the importer unflattens, and the SQLite
target is in memory. No sockets, no files in the repository.

What this suite pins, and the measured fact behind each rule (2026-10-30, one
detail page plus one ``/wefeed-h5api-bff/detail`` call):

* the site declares its renditions without publishing their URLs
  (``resource.seasons[].resolutions[]`` = 360/480/720/1080 with a per-season
  episode count; ``detailUrl``/``sniffUrl``/``sourceUrl`` are empty strings and
  ``dl`` is null). A declared rendition is stored as a release with an **empty**
  source list, because the vault saying "0 releases" for a work that lists four
  was the owner's complaint: the gap must be visible, not silent.
* a mirror under the site's ``dl``-shaped fields is stored with its status; a
  mirror the payload marks dead is stored as ``dead``, never discarded, per the
  Zero Data Loss rule. No populated ``dl`` has been captured live yet — this is
  the rule for the day one appears.
* an adult-labelled subject keeps its flag even though it has no playable print.
* a page with no links at all still yields its post with zero sources, and the
  export writes exactly that, so "scraped" can never be mistaken for "has links".
"""

from __future__ import annotations

import json
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import import_themoviebox as mb  # noqa: E402
from test_themoviebox_import import devalue, nuxt_script  # noqa: E402

DETAIL_URL = "https://themoviebox.xyz/detail/prison-break-mdR9oayBqn3"
MIRROR_URL = "https://ailok.pe/f/9f2c1e-Prison.Break.S01.1080p.mkv"

#: ``resource`` copied verbatim from the one detail page captured live on
#: 2026-10-30 (GET https://themoviebox.xyz/detail/prison-break-mdR9oayBqn3).
#: It declares 5 seasons × 4 tiers and names no URL anywhere: the same page and
#: its /wefeed-h5api-bff/detail answer both carry detailUrl/sniffUrl/sourceUrl
#: as empty strings and dl as null.
CAPTURED_RESOURCE = {
    "seasons": [
        {"se": 1, "maxEp": 22, "allEp": "", "resolutions": [
            {"resolution": 360, "epNum": 22}, {"resolution": 480, "epNum": 22},
            {"resolution": 720, "epNum": 22}, {"resolution": 1080, "epNum": 22}]},
        {"se": 2, "maxEp": 22, "allEp": "", "resolutions": [
            {"resolution": 360, "epNum": 22}, {"resolution": 480, "epNum": 22},
            {"resolution": 720, "epNum": 20}, {"resolution": 1080, "epNum": 21}]},
        {"se": 3, "maxEp": 13, "allEp": "", "resolutions": [
            {"resolution": 360, "epNum": 13}, {"resolution": 480, "epNum": 13},
            {"resolution": 720, "epNum": 13}, {"resolution": 1080, "epNum": 13}]},
        {"se": 4, "maxEp": 23, "allEp": "", "resolutions": [
            {"resolution": 360, "epNum": 23}, {"resolution": 480, "epNum": 23},
            {"resolution": 720, "epNum": 20}, {"resolution": 1080, "epNum": 23}]},
        {"se": 5, "maxEp": 9, "allEp": "", "resolutions": [
            {"resolution": 360, "epNum": 9}, {"resolution": 480, "epNum": 9},
            {"resolution": 720, "epNum": 6}, {"resolution": 1080, "epNum": 9}]},
    ],
    "source": "ailok.pe",
}

SERIES = {
    "subjectId": "2835060171381039112",
    "subjectType": 2,
    "title": "Prison Break",
    "releaseDate": "2005-08-29",
    "detailPath": "prison-break-mdR9oayBqn3",
    "detailUrl": "", "sniffUrl": "", "sourceUrl": "", "dl": None,
    "hasResource": True,
    "dubs": [{"lanName": "Original Audio", "lanCode": "en", "original": True},
             {"lanName": "Hindi dub", "lanCode": "hi", "original": False}],
    "resource": CAPTURED_RESOURCE,
}


def record_for(payload: dict) -> dict:
    records = mb.parse_page(nuxt_script(devalue(payload)), DETAIL_URL)
    assert len(records) == 1, records
    return records[0]


class DeclaredRenditionTests(unittest.TestCase):
    def test_each_rendition_becomes_one_release_with_no_sources(self):
        record = record_for(SERIES)
        pairs = [(rel["season"], rel["quality"]) for rel in record["releases"]]
        self.assertEqual(len(pairs), 20, "5 captured seasons × 4 captured tiers")
        self.assertEqual(pairs[:2], [(1, "360p"), (1, "480p")])
        self.assertEqual(pairs[-1], (5, "1080p"))
        self.assertTrue(all(rel["sources"] == [] for rel in record["releases"]),
                        "a tier whose URL is not published gets no source row")

    def test_release_carries_the_declared_episode_count_and_host(self):
        first = record_for(SERIES)["releases"][0]
        self.assertEqual(first["raw_meta"]["episodes"], 22)
        self.assertEqual(first["raw_meta"]["source_host"], "ailok.pe")
        self.assertIsNone(first["size_bytes"], "the site never publishes a size")
        self.assertIn("Hindi dub", first["audio"])

    def test_a_playable_url_still_wins_over_declared_tiers(self):
        payload = dict(SERIES, videoAddress={
            "url": "https://macdn.aoneroom.com/media/vone/x-1080.mp4"})
        releases = record_for(payload)["releases"]
        self.assertEqual(len(releases), 1)
        self.assertEqual(len(releases[0]["sources"]), 1,
                         "tiers must not be invented beside a real stream")


class MirrorTests(unittest.TestCase):
    def test_a_dead_mirror_is_stored_with_status_dead(self):
        payload = dict(SERIES, dl=[{"url": MIRROR_URL, "status": "dead"}])
        sources = [src for rel in record_for(payload)["releases"]
                   for src in rel["sources"]]
        self.assertEqual([(s["source_url"], s["status"]) for s in sources],
                         [(MIRROR_URL, "dead")])
        self.assertEqual(sources[0]["playback_type"], mb.PLAYBACK_DOWNLOAD)

    def test_a_live_mirror_is_stored_active_and_bound_to_its_quality(self):
        payload = dict(SERIES, dl=[{"url": MIRROR_URL, "available": True}])
        record = record_for(payload)
        bound = [rel for rel in record["releases"] if rel["sources"]]
        self.assertEqual(len(bound), 1, "one mirror, one release")
        self.assertEqual(bound[0]["quality"], "1080p")
        self.assertEqual([s["status"] for s in bound[0]["sources"]], ["active"])


class GapVisibilityTests(unittest.TestCase):
    def test_adult_label_survives_having_no_playable_print(self):
        payload = dict(SERIES, subjectId="999", title="Midnight Heat",
                       detailPath="midnight-heat-x1", isPornographic=True)
        record = record_for(payload)
        self.assertEqual(record["is_18_plus"], 1)
        self.assertTrue(record["releases"])

    def test_a_page_with_no_links_yields_the_post_with_zero_sources(self):
        bare = {k: v for k, v in SERIES.items() if k != "resource"}
        record = record_for(bare)
        self.assertEqual(record["releases"], [])

        conn = sqlite3.connect(":memory:")
        try:
            totals = mb.export_staging(conn=conn, posts=[record])
            releases = conn.execute("SELECT COUNT(*) FROM releases").fetchone()[0]
            sources = conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
            posts = conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual((posts, releases, sources), (1, 0, 0))
        self.assertEqual(totals["posts_written"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
