#!/usr/bin/env python3
"""
test_themoviebox_detail_api.py — the detail-API parser, offline.

Every fixture is the shape measured on 2026-10-30 from
``GET https://h5-api.aoneroom.com/wefeed-h5api-bff/detail?subjectId=2835060171381039112``
(200, ~39 KB, no credential) and from the same work's HTML detail page. No socket
is opened and no file is read from the repository.

What this suite pins, and the measured gap behind each rule:

* ``stars[]`` is where cast and crew live, and they are only distinguishable by
  ``character`` ("Director"/"Writer") and ``staffType`` (2/3); a person repeats
  once per season, so entries are de-duplicated by ``staffId``. The old parser
  read ``cast``/``actors``, saw neither, and stored NULL — while the payload
  carried 25 actors and 33 directors for this one series.
* ``dubs[]`` mixes audio with subtitles and says which via ``type`` (0/1), and
  ``subject.subtitles`` is a separate blob. Joining them erased the distinction.
* ``subject.stills`` is one image object, not a list, and it is the only wide
  image the site publishes — so an accepting-only-lists reader stored NULL
  ``backdrop_url``.
* ``seasons`` was computed before the declared renditions became releases, so a
  series whose only releases are declared stored ``seasons = NULL`` while its
  twenty releases each named a season.
* ``metadata.keyWords`` is a real field; when populated it must land somewhere.
* the trailer stays evidence, never a source, exactly as on the HTML path.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import import_themoviebox as mb  # noqa: E402
from test_themoviebox_import import devalue, nuxt_script  # noqa: E402
from test_themoviebox_links import CAPTURED_RESOURCE  # noqa: E402

DETAIL_URL = "https://themoviebox.xyz/detail/prison-break-mdR9oayBqn3"
COVER_URL = "https://pbcdnw.aoneroom.com/image/2026/03/30/aeeb26089be96a60bfce118097010f66.jpg"
STILL_URL = "https://pbcdnw.aoneroom.com/image/2023/03/23/842485cf90c16ec0df3930f9fd67c7e2.jpg"
TRAILER_URL = ("https://macdn.aoneroom.com/media/vone/2024/04/10/"
               "3cbde8714064faad7349794f2c8b8510-sd.mp4")
SYNOPSIS = ("A structural engineer installs himself in a prison he helped design, "
            "in order to save his falsely accused brother from a death sentence.")

#: Copied from the live answer. ``character``/``staffType`` are the only split
#: between actors and crew, and one person is listed twice under two spellings.
STARS = [
    {"staffId": "3458334022269557608", "staffType": 2,
     "name": "Bobby Roth", "character": "Director"},
    {"staffId": "7044494252390648312", "staffType": 2,
     "name": "Kevin Hooks", "character": "Director"},
    {"staffId": "9000000000000000001", "staffType": 2,
     "name": "Dwight H. Little", "character": "Director"},
    {"staffId": "9000000000000000002", "staffType": 3,
     "name": "Paul T. Scheuring", "character": "Writer"},
    {"staffId": "9000000000000000003", "staffType": 3,
     "name": "Nick Santora", "character": "Writer"},
    {"staffId": "1000000000000000001", "staffType": 1,
     "name": "Dominic Purcell", "character": "Lincoln Burrows"},
    {"staffId": "1000000000000000001", "staffType": 1,
     "name": "Dominic Purcell", "character": "Lincoln 'Linc' Burrows"},
    {"staffId": "1000000000000000002", "staffType": 1,
     "name": "Wentworth Miller", "character": "Michael Scofield"},
    {"staffId": "1000000000000000003", "staffType": 1,
     "name": "Sarah Wayne Callies", "character": "Sara Tancredi"},
    {"staffId": "1000000000000000004", "staffType": 1,
     "name": "Robert Knepper", "character": "Theodore 'T-Bag' Bagwell"},
]

SUBJECT = {
    "subjectId": "2835060171381039112",
    "subjectType": 2,
    "title": "Prison Break S1-S5",
    "description": SYNOPSIS,
    "releaseDate": "2005-08-29",
    "duration": 0,
    "genre": "Action,Crime,Drama",
    "cover": {"url": COVER_URL, "width": 513, "height": 755},
    "countryName": "United States",
    "imdbRatingValue": "8.3",
    "subtitles": "English,Español,Français,हिन्दी,中文",
    "hasResource": True,
    "trailer": {"videoAddress": {"url": TRAILER_URL, "duration": 126,
                                 "width": 848, "height": 476}},
    "detailPath": "prison-break-mdR9oayBqn3",
    "staffList": [],
    "stills": {"url": STILL_URL, "width": 1280, "height": 720},
    "postTitle": "Awesome!!!!!!!",
    "season": 0,
    "dubs": [
        {"lanName": "Original Audio", "lanCode": "en", "original": True, "type": 0},
        {"lanName": "French dub", "lanCode": "fr", "original": False, "type": 0},
        {"lanName": "Russian dub", "lanCode": "ru", "original": False, "type": 0},
        {"lanName": "Arabic sub", "lanCode": "ar", "original": False, "type": 1},
        {"lanName": "Indonesian sub", "lanCode": "id", "original": False, "type": 1},
    ],
    "accessStrategy": None,
    "webHighRisk": False,
    "isPornographic": False,
}
METADATA = {"title": "Prison Break", "description": SYNOPSIS,
            "keyWords": "", "image": COVER_URL}
DATA = {
    "subject": SUBJECT,
    "stars": STARS,
    "resource": CAPTURED_RESOURCE,
    "metadata": METADATA,
    "postList": {"pager": {"hasMore": True, "nextPage": "1"},
                 "items": [{"postId": "1", "title": "", "content": "hi"}]},
}
PAYLOAD = {"code": 0, "message": "ok", "data": DATA}


def record_for(payload=PAYLOAD) -> dict:
    records = mb.parse_detail_api(payload, DETAIL_URL)
    assert len(records) == 1, records
    return records[0]


class DetailApiRecordTests(unittest.TestCase):
    def test_the_subject_fields_are_read(self):
        record = record_for()
        self.assertEqual(record["title"], "Prison Break S1-S5")
        self.assertEqual(record["year"], 2005)
        self.assertEqual(record["media_type"], "series")
        self.assertEqual(record["poster_url"], COVER_URL)
        self.assertEqual(record["synopsis"], SYNOPSIS)
        self.assertEqual(record["genres"], "Action,Crime,Drama")
        self.assertEqual(record["is_18_plus"], 0)
        self.assertEqual(record["url"], DETAIL_URL)

    def test_a_payload_that_is_not_a_detail_answer_is_refused(self):
        self.assertEqual(mb.parse_detail_api({"code": 0, "data": {}}, DETAIL_URL), [])
        self.assertEqual(mb.parse_detail_api({"code": 401, "message": "auth"},
                                             DETAIL_URL), [])
        self.assertEqual(mb.parse_detail_api(None, DETAIL_URL), [])


class DeclaredTierTests(unittest.TestCase):
    def test_every_declared_tier_is_a_release_with_no_source(self):
        record = record_for()
        pairs = [(rel["season"], rel["quality"]) for rel in record["releases"]]
        self.assertEqual(len(pairs), 20, "5 captured seasons × 4 captured tiers")
        self.assertEqual(pairs[0], (1, "360p"))
        self.assertEqual(pairs[-1], (5, "1080p"))
        self.assertTrue(all(rel["sources"] == [] for rel in record["releases"]))
        self.assertTrue(all(rel["raw_meta"]["declared"] for rel in record["releases"]))

    def test_per_season_episode_counts_are_kept_on_the_post(self):
        renditions = record_for()["raw_meta"]["declared_renditions"]
        self.assertEqual(len(renditions), 20)
        season_two_720 = [r for r in renditions
                          if r["season"] == 2 and r["resolution"] == 720]
        self.assertEqual(season_two_720[0]["episodes"], 20,
                         "measured: S2 720p declares 20 episodes, not 22")
        self.assertEqual(season_two_720[0]["source_host"], "ailok.pe")

    def test_seasons_are_stamped_after_the_renditions_land(self):
        record = record_for()
        self.assertEqual(json.loads(record["seasons"]), [1, 2, 3, 4, 5])
        self.assertEqual(sorted({rel["season"] for rel in record["releases"]}),
                         [1, 2, 3, 4, 5])


class ArtworkTests(unittest.TestCase):
    def test_a_stills_object_becomes_the_backdrop(self):
        record = record_for()
        self.assertEqual(record["backdrop_url"], STILL_URL,
                         "stills is one image object and the only wide image")
        self.assertIn(STILL_URL, json.loads(record["backdrop_urls"]))
        self.assertEqual(record["poster_url"], COVER_URL)


class CreditTests(unittest.TestCase):
    def test_cast_excludes_crew_and_is_deduplicated_by_staff_id(self):
        record = record_for()
        cast = [n.strip() for n in record["cast_names"].split(",")]
        self.assertEqual(cast, ["Dominic Purcell", "Wentworth Miller",
                                "Sarah Wayne Callies", "Robert Knepper"])
        self.assertNotIn("Bobby Roth", record["cast_names"])

    def test_directors_from_the_character_field(self):
        record = record_for()
        self.assertEqual(record["director"],
                         "Bobby Roth, Kevin Hooks, Dwight H. Little")

    def test_writers_are_kept_as_evidence(self):
        record = record_for()
        self.assertEqual(record["raw_meta"]["writers"],
                         "Paul T. Scheuring, Nick Santora")


class LanguageTests(unittest.TestCase):
    def test_audio_and_subtitles_are_split_by_dub_type(self):
        record = record_for()
        self.assertEqual(record["languages"],
                         "Original Audio, French dub, Russian dub")
        subs = record["raw_meta"]["subtitles"]
        self.assertIn("Arabic sub", subs)
        self.assertIn("Indonesian sub", subs)
        self.assertIn("English", subs, "subject.subtitles blob also lands")
        self.assertNotIn("sub", record["languages"].lower())


class KeywordTests(unittest.TestCase):
    def test_populated_keywords_land_in_raw_meta(self):
        payload = {"code": 0, "data": dict(
            DATA, metadata=dict(METADATA, keyWords="prison, escape, brothers"))}
        record = record_for(payload)
        self.assertEqual(record["raw_meta"]["keywords"], "prison, escape, brothers")

    def test_empty_keywords_are_not_invented(self):
        self.assertNotIn("keywords", record_for()["raw_meta"])


class TrailerTests(unittest.TestCase):
    def test_the_trailer_is_evidence_and_never_a_source(self):
        record = record_for()
        self.assertEqual(record["raw_meta"]["trailer_url"], TRAILER_URL)
        urls = [src["source_url"] for rel in record["releases"]
                for src in rel["sources"]]
        self.assertNotIn(TRAILER_URL, urls)
        self.assertEqual(urls, [])


class StagingTests(unittest.TestCase):
    def test_export_writes_the_rows_with_zero_sources(self):
        record = record_for()
        conn = sqlite3.connect(":memory:")
        try:
            totals = mb.export_staging(conn=conn, posts=[record])
            self.assertEqual(totals["posts_written"], 1)
            self.assertEqual(totals["releases_written"], 20)
            self.assertEqual(totals["sources_written"], 0)

            row = conn.execute(
                "SELECT backdrop_url, director, cast_names, seasons, languages"
                " FROM posts").fetchone()
            self.assertEqual(row[0], STILL_URL)
            self.assertEqual(row[1], "Bobby Roth, Kevin Hooks, Dwight H. Little")
            self.assertIn("Dominic Purcell", row[2])
            self.assertEqual(json.loads(row[3]), [1, 2, 3, 4, 5])
            self.assertEqual(row[4], "Original Audio, French dub, Russian dub")

            rel = conn.execute(
                "SELECT season_number, episode_number, quality, audio_languages"
                " FROM releases ORDER BY id LIMIT 1").fetchone()
            self.assertEqual(rel[0], 1)
            self.assertIsNone(rel[1], "a season tier declares no single episode")
            self.assertEqual(rel[2], "360p")

            meta = json.loads(conn.execute(
                "SELECT raw_meta FROM releases ORDER BY id LIMIT 1").fetchone()[0])
            self.assertEqual(meta["episodes"], 22)
        finally:
            conn.close()


class HtmlPathTests(unittest.TestCase):
    def test_the_page_payload_gets_the_same_evidence(self):
        # The Nuxt page hydrates the detail answer under a data key; the credits
        # and keywords sit beside `subject`, where per-anchor lookups cannot see
        # them. This pins the shared fix on the HTML path too.
        page = {"data": {"subject": SUBJECT, "stars": STARS,
                         "metadata": METADATA, "resource": CAPTURED_RESOURCE}}
        records = mb.parse_page(nuxt_script(devalue(page)), DETAIL_URL)
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["backdrop_url"], STILL_URL)
        self.assertEqual(record["director"],
                         "Bobby Roth, Kevin Hooks, Dwight H. Little")
        self.assertIn("Dominic Purcell", record["cast_names"])
        self.assertEqual(json.loads(record["seasons"]), [1, 2, 3, 4, 5])
        self.assertEqual(record["languages"],
                         "Original Audio, French dub, Russian dub")


class CrawlSurfaceTests(unittest.TestCase):
    """The queue decides the surface: a stored subjectId reads the JSON endpoint."""

    def _seed(self, db, raw_json):
        conn = sqlite3.connect(db)
        try:
            mb.ensure_schema(conn)
            conn.execute(
                "INSERT INTO sitemap_cache (loc, lastmod, slug, scraped,"
                " raw_json, error_count) VALUES (?, ?, ?, 0, ?, 0)",
                (DETAIL_URL, None, "prison-break-mdR9oayBqn3", raw_json))
            conn.commit()
        finally:
            conn.close()

    def _crawl(self, db, body, status=200):
        calls = []

        def fake_get(url, **kwargs):
            calls.append(url)
            return status, url, body

        with mock.patch.object(mb, "http_get", fake_get), \
                mock.patch.object(mb, "memory_ok", return_value=(True, "ok")):
            totals = mb.crawl_pending(db_path=db, workers=1, delay=0)
        return totals, calls

    def test_a_queued_subject_id_reads_the_json_detail_endpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "vault.db"
            self._seed(db, json.dumps({"subjectId": SUBJECT["subjectId"]}))
            totals, calls = self._crawl(db, json.dumps(PAYLOAD))
            self.assertEqual(calls,
                             [mb.detail_api_url(SUBJECT["subjectId"])])
            self.assertIn("subjectId=", calls[0])
            self.assertEqual(totals["api_pages"], 1)
            self.assertEqual(totals["releases"], 20)
            self.assertEqual(totals["sources"], 0)
            with closing(sqlite3.connect(db)) as conn:
                row = conn.execute(
                    "SELECT seasons, backdrop_url, director FROM posts").fetchone()
                self.assertEqual(json.loads(row[0]), [1, 2, 3, 4, 5])
                self.assertEqual(row[1], STILL_URL)
                self.assertEqual(row[2], "Bobby Roth, Kevin Hooks, Dwight H. Little")
                self.assertEqual(conn.execute(
                    "SELECT COUNT(*) FROM sitemap_cache WHERE scraped = 1"
                ).fetchone()[0], 1)

    def test_a_legacy_row_without_subject_id_reads_its_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "vault.db"
            self._seed(db, "{}")
            page = nuxt_script(devalue({"data": DATA}))
            totals, calls = self._crawl(db, page)
            self.assertEqual(calls, [DETAIL_URL])
            self.assertEqual(totals["api_pages"], 0)
            self.assertEqual(totals["releases"], 20)

    def test_a_non_detail_answer_fails_the_row_instead_of_inventing_a_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "vault.db"
            self._seed(db, json.dumps({"subjectId": SUBJECT["subjectId"]}))
            totals, _calls = self._crawl(
                db, json.dumps({"code": 401, "message": "login required"}))
            self.assertEqual(totals["failed_rows"], 1)
            self.assertEqual(totals["releases"], 0)
            with closing(sqlite3.connect(db)) as conn:
                scraped, errors, raw = conn.execute(
                    "SELECT scraped, error_count, raw_json FROM sitemap_cache"
                ).fetchone()
                self.assertEqual(scraped, 2, "retryable: PENDING_SELECT keeps it")
                self.assertEqual(errors, 1)
                self.assertEqual(json.loads(raw)["subjectId"],
                                 SUBJECT["subjectId"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
