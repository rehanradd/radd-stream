#!/usr/bin/env python3
"""
test_themoviebox_import.py — offline unit tests for the themoviebox.xyz importer.

No test touches the network: every fetch is mocked and every fixture is shaped
from pages measured on this host on 2026-10-29. The rules this suite keeps, and
the measured defect each one exists because of:

* a trailer is never a playable print. The site serves ``trailer.videoAddress``
  from the same ``macdn.aoneroom.com`` edge, in the same ``…-ld.mp4`` shape as a
  real print, so only its position in the graph distinguishes them. Before this
  rule, a live movie page parsed into 2 releases whose only URL was a 169-second
  640x360 preview.
* a work with no print is a valid row, recorded metadata-only and marked crawled.
  The play URL is resolved client-side (``detailUrl``/``sniffUrl``/``sourceUrl``
  are all empty strings in the payload), so treating "no media" as a scrape
  failure would park the entire catalog after three attempts.
* ``subjectType`` decides movie vs series. Deriving it from "does some dict carry
  a season" made every film a series, because a movie's payload contains
  ``season: 0`` and ``seasons: [{se: 0, maxEp: 0}]``.
* ``subjectType`` 6 is a music mix, not a work, and is not ingested.
* a work is a dict with a ``title`` **and** a route (``detailPath``/``subjectId``).
  A name alone matched cast members: one live page parsed into 19 records, 18 of
  them people and banner wrappers.
* discovery is the paginated catalog feed, not ``/sitemap.xml``, which answers a
  real HTTP 404 here.
* a reset connection is retried hard, an HTTP answer is not retried at all beyond
  one attempt, because the edge resets ~2 of 3 handshakes from this host.
"""

from __future__ import annotations

import contextlib
import io
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import import_themoviebox as mb  # noqa: E402

DETAIL_URL = "https://themoviebox.xyz/detail/matchbox-the-movie-S5hfykcX3Z4"
TRAILER_URL = ("https://macdn.aoneroom.com/media/vone/2026-09-22/"
               "963d1683d5c57143436f2dfa070972bf-ld.mp4")
PRINT_URL = ("https://macdn.aoneroom.com/media/vone/2026-09-22/"
             "abcdef0123456789abcdef0123456789-hd.mp4")


def nuxt_script(payload) -> str:
    """Wraps a hydrated-shape object the way Nuxt ships it: as __NUXT_DATA__ JSON."""
    return ('<!DOCTYPE html><html><head><script id="__NUXT_DATA__" type="application/json">'
            + json.dumps(payload) + "</script></head><body></body></html>")


def devalue(subject: dict) -> list:
    """Encodes one dict as a devalue flat pool, the way the site actually ships it.

    Every value becomes an index into the pool, so this also proves ``unflatten``
    against the real indirection rather than against a shape that happens to work.
    Containers get a slot each and are never shared: two empty ``{}`` members are
    two different objects in the graph, and collapsing them would encode a payload
    the site does not produce.
    """
    pool: list = [None]

    def slot(value) -> int:
        pool.append(value)
        return len(pool) - 1

    def encode(value):
        if isinstance(value, dict):
            node = {}
            position = slot(node)
            for key, child in value.items():
                node[key] = encode(child)
            return position
        if isinstance(value, list):
            node = []
            position = slot(node)
            for child in value:
                node.append(encode(child))
            return position
        if isinstance(value, str):
            # Strings sit in their own slot; only scalars may be shared.
            return slot(value)
        return slot(value)

    encoded = {}
    pool[0] = encoded
    for key, value in subject.items():
        encoded[key] = encode(value)
    return pool


MATCHBOX = {
    "subjectId": "4183823238805478232",
    "subjectType": 1,
    "title": "Matchbox the Movie",
    "description": "Childhood friends reconnect.",
    "releaseDate": "2026-10-09",
    "duration": 7560,
    "genre": "Action,Adventure,Comedy",
    "cover": {"url": "https://pbcdnw.aoneroom.com/image/2026/10/13/a.jpg",
              "width": 2000, "height": 3000},
    "countryName": "United States",
    "imdbRatingValue": "5.7",
    "subtitles": "English,Hindi",
    "hasResource": True,
    "detailPath": "matchbox-the-movie-S5hfykcX3Z4",
    "detailUrl": "", "sniffUrl": "", "sourceUrl": "", "dl": None,
    "postTitle": "Matchbox-1080P",
    "isPornographic": False,
    "webHighRisk": False,
    "season": 0,
    "dubs": [{"lanName": "Original Audio", "lanCode": "en", "original": True,
              "detailPath": "matchbox-the-movie-S5hfykcX3Z4"},
             {"lanName": "French dub", "lanCode": "fr", "original": False,
              "detailPath": "matchbox-the-movie-Emxcdo4ZHj8"}],
    "staffList": [{"staffId": "1", "staffType": 1, "name": "John Cena"}],
    "trailer": {"videoAddress": {"videoId": "7756806793267134592",
                                 "url": TRAILER_URL, "duration": 169,
                                 "width": 640, "height": 360}},
}

#: The same work with the resource node beside it — the shape a live detail page
#: carries: tiers named, URLs absent.
MATCHBOX_WITH_RESOURCE = dict(MATCHBOX, **{
    "resource": {"seasons": [{"se": 0, "maxEp": 0, "allEp": "",
                              "resolutions": [{"resolution": 360, "epNum": 1},
                                              {"resolution": 480, "epNum": 1},
                                              {"resolution": 1080, "epNum": 1}]}],
                 "source": "fzmovies.cms"},
})

PAWANI = dict(MATCHBOX, **{
    "subjectId": "999", "title": "Midnight Heat", "detailPath": "midnight-heat-x1",
    "isPornographic": True, "webHighRisk": False,
})


def silenced():
    return contextlib.redirect_stdout(io.StringIO())


class UnflattenTests(unittest.TestCase):
    def test_reconstructs_the_nested_subject_from_a_real_flat_pool(self):
        data = mb.extract_nuxt_payload(nuxt_script(devalue(MATCHBOX)))
        self.assertEqual(data["title"], "Matchbox the Movie")
        self.assertEqual(data["cover"]["url"],
                         "https://pbcdnw.aoneroom.com/image/2026/10/13/a.jpg")
        self.assertEqual(data["trailer"]["videoAddress"]["url"], TRAILER_URL)
        self.assertEqual(data["dubs"][1]["lanName"], "French dub")

    def test_plain_json_object_is_passed_through(self):
        self.assertEqual(mb.unflatten({"a": 1}), {"a": 1})

    def test_special_slots_become_none_not_the_string_none(self):
        pool = [{"a": -1, "b": -3}]
        out = mb.unflatten(pool)
        self.assertIsNone(out["a"])
        self.assertTrue(out["b"] != out["b"], "NaN must stay NaN")

    def test_cycles_terminate(self):
        pool = [{"self": 0}]
        out = mb.unflatten(pool)
        self.assertIs(out["self"], out)


class ParsePageTests(unittest.TestCase):
    def test_one_work_per_detail_page_not_one_per_appearance(self):
        records = mb.parse_page(nuxt_script(devalue(MATCHBOX)), DETAIL_URL)
        self.assertEqual(len(records), 1, records)

    def test_cast_members_are_never_works(self):
        """The live page produced 19 records for one film; 18 were people/banners."""
        records = mb.parse_page(nuxt_script(devalue(MATCHBOX)), DETAIL_URL)
        titles = {r["title"] for r in records}
        self.assertNotIn("John Cena", titles)

    def test_a_trailer_is_never_a_playable_print(self):
        records = mb.parse_page(nuxt_script(devalue(MATCHBOX)), DETAIL_URL)
        record = records[0]
        self.assertEqual(record["releases"], [],
                         "a trailer must not become a release")
        self.assertEqual(record["raw_meta"]["trailer_url"], TRAILER_URL,
                         "and must still be recorded as evidence")
        self.assertEqual(mb.parse_page(
            nuxt_script(devalue(MATCHBOX)), DETAIL_URL)[0]["media_type"], "movie")

    def test_a_real_print_under_a_playable_key_is_still_collected(self):
        subject = dict(MATCHBOX, videoAddress={"url": PRINT_URL, "duration": 7560})
        record = mb.parse_page(nuxt_script(devalue(subject)), DETAIL_URL)[0]
        self.assertEqual(len(record["releases"]), 1)
        self.assertEqual(record["releases"][0]["sources"][0]["source_url"],
                         PRINT_URL)
        self.assertEqual(record["releases"][0]["quality"], "HD")

    def test_duplicate_media_urls_do_not_duplicate_releases(self):
        subject = dict(MATCHBOX, videoAddress={"url": PRINT_URL},
                       episodes=[{"videoAddress": {"url": PRINT_URL}}])
        record = mb.parse_page(nuxt_script(devalue(subject)), DETAIL_URL)[0]
        urls = [rel["sources"][0]["source_url"] for rel in record["releases"]]
        self.assertEqual(len(urls), len(set(urls)), urls)

    def test_non_cdn_media_is_dropped(self):
        subject = dict(MATCHBOX, videoAddress={
            "url": "https://ad.example.com/spot-ld.mp4"})
        record = mb.parse_page(nuxt_script(devalue(subject)), DETAIL_URL)[0]
        self.assertEqual(record["releases"], [])

    def test_subject_type_wins_over_episode_shaped_keys(self):
        self.assertEqual(mb._media_type(mb.SUBJECT_TYPE_MOVIE,
                                        [{"season": 3, "episode": 2}]), "movie")
        self.assertEqual(mb._media_type(mb.SUBJECT_TYPE_SERIES, []), "series")

    def test_zero_is_not_a_season_number(self):
        self.assertIsNone(mb._positive_int(0))
        self.assertEqual(mb._positive_int("7"), 7)
        self.assertIsNone(mb._positive_int(True))
        self.assertIsNone(mb._positive_int(None))

    def test_season_zero_does_not_make_a_movie_a_series(self):
        record = mb.parse_page(nuxt_script(devalue(MATCHBOX)), DETAIL_URL)[0]
        self.assertEqual(record["media_type"], "movie")
        self.assertIsNone(record["seasons"])

    def test_music_mixes_are_not_ingested(self):
        mix = dict(MATCHBOX, subjectId="777", subjectType=6,
                   title="Best of X — 2 Hour Mix", detailPath="mix-1")
        self.assertEqual(mb.parse_page(nuxt_script(devalue(mix)),
                                      "https://themoviebox.xyz/detail/mix-1"), [])

    def test_adult_flag_on_the_subject_survives_having_no_media(self):
        """The flag lives on the subject and this site's works have no media, so a
        candidates-only check would publish an isPornographic title unflagged."""
        record = mb.parse_page(nuxt_script(devalue(PAWANI)),
                              "https://themoviebox.xyz/detail/midnight-heat-x1")[0]
        self.assertEqual(record["is_18_plus"], 1)

    def test_web_high_risk_sets_the_flag(self):
        risky = dict(MATCHBOX, subjectId="998", webHighRisk=True)
        self.assertEqual(mb.parse_page(nuxt_script(devalue(risky)), DETAIL_URL
                                       )[0]["is_18_plus"], 1)

    def test_midnight_shelf_is_flagged_by_route(self):
        record = mb.parse_page(nuxt_script(devalue(MATCHBOX)),
                              "https://themoviebox.xyz/web/midnight/foo")[0]
        self.assertEqual(record["is_18_plus"], 1)

    def test_metadata_fields_come_from_the_measured_keys(self):
        record = mb.parse_page(
            nuxt_script(devalue(MATCHBOX_WITH_RESOURCE)), DETAIL_URL)[0]
        self.assertEqual(record["year"], 2026)
        self.assertEqual(record["imdb_rating"], "5.7")
        self.assertEqual(record["genres"], "Action,Adventure,Comedy")
        self.assertEqual(record["country"], "United States")
        self.assertEqual(record["poster_url"],
                         "https://pbcdnw.aoneroom.com/image/2026/10/13/a.jpg")
        self.assertIn("Original Audio", record["languages"])
        self.assertEqual(record["duration"], "7560")

    def test_artwork_is_read_out_of_the_image_object(self):
        self.assertEqual(mb._image_url({"url": "https://x/a.jpg"}),
                         "https://x/a.jpg")
        self.assertEqual(mb._image_url("https://x/b.jpg"), "https://x/b.jpg")
        self.assertIsNone(mb._image_url({}))
        self.assertEqual(mb._image_list(None), [])
        self.assertEqual(mb._image_list([{"url": "https://x/1.jpg"}, "junk",
                                        {"nope": 1}]), ["https://x/1.jpg"])

    def test_tiers_are_recorded_as_evidence_and_not_as_links(self):
        record = mb.parse_page(
            nuxt_script(devalue(MATCHBOX_WITH_RESOURCE)), DETAIL_URL)[0]
        self.assertEqual(record["raw_meta"]["available_resolutions"],
                         [1080, 480, 360])
        self.assertEqual(record["releases"], [])

    def test_a_page_without_the_nuxt_block_yields_nothing(self):
        self.assertEqual(mb.parse_page("<html><body>no payload</body></html>",
                                      DETAIL_URL), [])

    def test_an_unroutable_title_alone_is_not_a_work(self):
        self.assertEqual(mb.parse_page(
            nuxt_script(devalue({"title": "Section heading", "description": "x"})),
            DETAIL_URL), [])


class DiscoveryTests(unittest.TestCase):
    def test_detail_url_is_built_the_way_the_site_links_it(self):
        self.assertEqual(mb._detail_url(MATCHBOX), DETAIL_URL)
        self.assertIsNone(mb._detail_url({"title": "no path"}))

    def _feed(self, items, pager=None):
        """The first request answers with `items`; every later one ends the catalog.

        The walker visits one page per accepted subject type, so a fake that only
        answers once makes the second type raise StopIteration inside the code
        under test and report a discovery bug that is not there.
        """
        first = (200, {"code": 0, "message": "ok", "data": {
            "items": items, "pager": pager or {"hasMore": False,
                                                "nextPage": "2"}}})
        done = (200, {"code": 0, "message": "ok",
                      "data": {"items": [], "pager": {"hasMore": False}}})

        def side_effect(*args, **kwargs):
            side_effect.calls += 1
            return first if side_effect.calls == 1 else done

        side_effect.calls = 0
        return mock.MagicMock(side_effect=side_effect)

    def test_sync_walks_the_feed_not_a_sitemap(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "v.db"
            with silenced(), mock.patch.object(
                    mb, "_api_request",
                    self._feed([MATCHBOX, PAWANI])) as api:
                totals = mb.sync_catalog(db)
            self.assertEqual(totals["queued"], 2, totals)
            self.assertNotIn("sitemap.xml", json.dumps(api.call_args_list),
                             "the sitemap path is a 404 on this site")
            conn = sqlite3.connect(db)
            locs = {row[0] for row in conn.execute(
                "SELECT loc FROM sitemap_cache")}
            conn.close()
            self.assertIn(DETAIL_URL, locs)

    def test_a_dub_of_an_already_queued_work_is_not_queued_again(self):
        french = dict(MATCHBOX, subjectId="500",
                      detailPath="matchbox-the-movie-Emxcdo4ZHj8")
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "v.db"
            with silenced(), mock.patch.object(mb, "_api_request",
                                               self._feed([MATCHBOX, french])):
                totals = mb.sync_catalog(db)
            self.assertEqual(totals["queued"], 1, totals)
            self.assertEqual(totals["duplicates"], 1, totals)

    def test_feed_error_stops_instead_of_loopping(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "v.db"
            api = mock.MagicMock(return_value=(400, None))
            with silenced(), mock.patch.object(mb, "_api_request", api):
                totals = mb.sync_catalog(db)
            self.assertEqual(totals["queued"], 0)
            self.assertEqual(api.call_count, 1, "one failure per type, no retry storm")

    def test_harvest_writes_metadata_only_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "v.db"
            with silenced(), mock.patch.object(
                    mb, "_api_request", self._feed([MATCHBOX_WITH_RESOURCE])):
                totals = mb.harvest_catalog(db)
            self.assertEqual(totals["posts"], 1, totals)
            conn = sqlite3.connect(db)
            conn.row_factory = sqlite3.Row
            post = conn.execute("SELECT * FROM posts").fetchone()
            releases = conn.execute("SELECT COUNT(*) FROM releases").fetchone()[0]
            sources = conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
            conn.close()
            self.assertEqual(releases, 0)
            self.assertEqual(sources, 0, "no trailer may reach the sources table")
            self.assertEqual(post["title"], "Matchbox the Movie")
            self.assertEqual(post["media_type"], "movie")
            self.assertIn("trailer_url", post["raw_meta"])


class HttpTests(unittest.TestCase):
    """The edge resets ~2 of 3 handshakes, so the retry shape is load-bearing."""

    def _urlopen_sequence(self, seq):
        """An urlopen that replays `seq`: an Exception raises, a str becomes a body."""
        class Response:
            status = 200

            def __init__(self, body):
                self.body = body

            def read(self):
                return self.body.encode()

            def geturl(self):
                return "https://themoviebox.xyz/x"

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        calls = []

        def urlopen(request, timeout=None):
            item = seq[len(calls)] if len(calls) < len(seq) else seq[-1]
            calls.append(item)
            if isinstance(item, Exception):
                raise item
            return Response(item)
        return urlopen, calls

    def test_transport_failures_are_retried_until_success(self):
        seq = [Exception("reset"), Exception("reset"), "BODY"]
        urlopen, calls = self._urlopen_sequence(seq)

        with mock.patch.object(mb.urllib.request, "urlopen", urlopen), \
                mock.patch.object(mb.time, "sleep", lambda *_: None), \
                mock.patch.object(mb, "_throttle", lambda *_: None):
            status, _final, body = mb.http_get("https://themoviebox.xyz/x",
                                              delay=0)
        self.assertEqual(status, 200)
        self.assertEqual(body, "BODY")
        self.assertEqual(len(calls), 3)

    def test_http_404_is_not_retried_into_oblivion(self):
        error = mb.urllib.error.HTTPError("https://x", 404, "Not Found", {}, None)
        calls = []

        def urlopen(request, timeout=None):
            calls.append(1)
            raise error

        with mock.patch.object(mb.urllib.request, "urlopen", urlopen), \
                mock.patch.object(mb.time, "sleep", lambda *_: None), \
                mock.patch.object(mb, "_throttle", lambda *_: None):
            status, _final, body = mb.http_get("https://themoviebox.xyz/x", delay=0)
        self.assertEqual(status, 404)
        self.assertLessEqual(len(calls), mb.HTTP_ERROR_RETRIES + 1,
                            "an origin answer is evidence, not a flap")

    def test_connections_per_page_are_capped(self):
        def urlopen(request, timeout=None):
            raise Exception("reset forever")

        with mock.patch.object(mb.urllib.request, "urlopen", urlopen), \
                mock.patch.object(mb.time, "sleep", lambda *_: None), \
                mock.patch.object(mb, "_throttle", lambda *_: None):
            status, _final, body = mb.http_get("https://themoviebox.xyz/x", delay=0)
        self.assertEqual(status, 0)
        self.assertLessEqual(mb.MAX_CONNECTIONS_PER_PAGE, 9)

    def test_every_attempt_pays_the_politeness_floor(self):
        seen = []

        def urlopen(request, timeout=None):
            raise Exception("reset")

        with mock.patch.object(mb.urllib.request, "urlopen", urlopen), \
                mock.patch.object(mb.time, "sleep", lambda *_: None), \
                mock.patch.object(mb, "_throttle", lambda d: seen.append(d)):
            mb.http_get("https://themoviebox.xyz/x", delay=0.3)
        self.assertGreaterEqual(len(seen), 2, "retries must not bypass the throttle")
        self.assertTrue(all(value == 0.3 for value in seen))


class CrawlTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "v.db"
        conn = sqlite3.connect(self.db)
        mb.ensure_schema(conn)
        conn.execute("INSERT INTO sitemap_cache (loc, scraped, raw_json, error_count)"
                     " VALUES (?, 0, '{}', 0)", (DETAIL_URL,))
        conn.commit()
        conn.close()
        self.addCleanup(self.tmp.cleanup)

    def test_metadata_only_pages_are_crawled_not_parked(self):
        html = nuxt_script(devalue(MATCHBOX_WITH_RESOURCE))
        with silenced(), mock.patch.object(mb, "http_get",
                                          return_value=(200, DETAIL_URL, html)), \
                mock.patch.object(mb, "memory_ok", return_value=(True, "ok")), \
                mock.patch.object(mb.time, "sleep", lambda *_: None):
            totals = mb.crawl_pending(db_path=self.db, workers=1, delay=0)
        self.assertEqual(totals["metadata_only"], 1, totals)
        self.assertEqual(totals["failed_rows"], 0)
        conn = sqlite3.connect(self.db)
        state = conn.execute("SELECT scraped, error_count FROM sitemap_cache"
                             " WHERE loc = ?", (DETAIL_URL,)).fetchone()
        posts = conn.execute("SELECT title, is_18_plus FROM posts").fetchall()
        sources = conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
        conn.close()
        self.assertEqual(state[0], 1, "crawled, so a re-run stops refetching it")
        self.assertEqual(state[1], 0)
        self.assertEqual(posts, [("Matchbox the Movie", 0)])
        self.assertEqual(sources, 0)

    def test_a_page_that_names_no_work_is_an_error_and_is_counted(self):
        with silenced(), mock.patch.object(mb, "http_get",
                                          return_value=(200, DETAIL_URL, "<html>x")), \
                mock.patch.object(mb, "memory_ok", return_value=(True, "ok")), \
                mock.patch.object(mb.time, "sleep", lambda *_: None):
            totals = mb.crawl_pending(db_path=self.db, workers=1, delay=0)
        self.assertEqual(totals["failed_rows"], 1)
        conn = sqlite3.connect(self.db)
        state = conn.execute("SELECT scraped, error_count FROM sitemap_cache"
                             " WHERE loc = ?", (DETAIL_URL,)).fetchone()
        conn.close()
        self.assertEqual(state, (2, 1), "retryable, and the failure is ledgered")

    def test_429_pauses_without_consuming_the_queue(self):
        with silenced(), mock.patch.object(mb, "http_get",
                                          return_value=(429, DETAIL_URL, "")), \
                mock.patch.object(mb, "memory_ok", return_value=(True, "ok")), \
                mock.patch.object(mb.time, "sleep", lambda *_: None):
            totals = mb.crawl_pending(db_path=self.db, workers=1, delay=0)
        self.assertTrue(totals["paused_rate_limit"])
        conn = sqlite3.connect(self.db)
        state = conn.execute("SELECT scraped FROM sitemap_cache WHERE loc = ?",
                             (DETAIL_URL,)).fetchone()[0]
        conn.close()
        self.assertEqual(state, 0, "a rate-limited row stays queued, not parked")

    def test_the_crawl_refuses_to_start_when_the_box_is_low_on_memory(self):
        with silenced(), mock.patch.object(
                mb, "memory_ok",
                return_value=(False, "MemAvailable 900 MB < 2500 MB")):
            totals = mb.crawl_pending(db_path=self.db, workers=1, delay=0)
        self.assertTrue(totals["stopped_for_memory"])
        conn = sqlite3.connect(self.db)
        state = conn.execute("SELECT scraped FROM sitemap_cache WHERE loc = ?",
                             (DETAIL_URL,)).fetchone()[0]
        conn.close()
        self.assertEqual(state, 0, "nothing may be consumed by a refused run")

    def test_workers_are_clamped_so_a_typo_cannot_stampede_the_edge(self):
        self.assertEqual(mb._clamp_workers(None), mb.DEFAULT_WORKERS)
        self.assertEqual(mb._clamp_workers(0), 1)
        self.assertEqual(mb._clamp_workers(9999), mb.MAX_WORKERS)


class SchemaAndMemoryTests(unittest.TestCase):
    def test_memory_floor_reads_real_meminfo(self):
        ok, reason = mb.memory_ok("MemAvailable:   5900000 kB\nSwapFree:  3000000 kB\n")
        self.assertTrue(ok, reason)
        ok, _reason = mb.memory_ok("MemAvailable:   900000 kB\nSwapFree:  3000000 kB\n")
        self.assertFalse(ok)
        ok, _reason = mb.memory_ok("MemAvailable:   9000000 kB\nSwapFree:   10000 kB\n")
        self.assertFalse(ok)

    def test_schema_migration_is_additive_and_idempotent(self):
        """A vault written by the previous revision must upgrade in place."""
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "old.db"
            conn = sqlite3.connect(db)
            conn.executescript(
                "CREATE TABLE posts (canonical_key TEXT PRIMARY KEY,"
                " title TEXT NOT NULL, clean_title TEXT NOT NULL);"
                "CREATE TABLE releases (id INTEGER PRIMARY KEY,"
                " post_canonical_key TEXT);"
                "CREATE TABLE sources (id INTEGER PRIMARY KEY, release_id INTEGER);")
            conn.execute("INSERT INTO posts VALUES ('k', 'Old Row', 'Old Row')")
            conn.commit()
            mb.ensure_schema(conn)
            mb.ensure_schema(conn)
            columns = {row[1] for row in conn.execute("PRAGMA table_info(posts)")}
            # ensure_schema installs row_factory, so read the value, not the Row.
            rows = [row[0] for row in conn.execute("SELECT title FROM posts")]
            conn.close()
            self.assertTrue({"year", "is_18_plus", "source_site"} <= columns,
                            sorted(columns))
            self.assertEqual(rows, ["Old Row"], "migration must not lose data")

    def test_export_replaces_only_the_page_it_rewrites(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "v.db"
            record = mb.parse_page(nuxt_script(devalue(dict(
                MATCHBOX, videoAddress={"url": PRINT_URL}))), DETAIL_URL)[0]
            first = dict(record, url="https://themoviebox.xyz/detail/a")
            keep = dict(record, canonical_key="other_2020", title="Other",
                        clean_title="Other",
                        url="https://themoviebox.xyz/detail/b")
            totals = mb.export_staging(db, [first, keep])
            self.assertEqual(totals["sources_written"], 2, totals)
            # Re-export one page: its own release goes and comes back, the other's
            # stays — the bug this guards is deleting earlier rows of the same page.
            totals = mb.export_staging(db, [first])
            conn = sqlite3.connect(db)
            keys = {row[0] for row in conn.execute(
                "SELECT DISTINCT post_canonical_key FROM releases")}
            posts = conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
            conn.close()
            self.assertEqual(posts, 2)
            self.assertEqual(keys, {first["canonical_key"], keep["canonical_key"]})

    def test_posts_without_releases_survive_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "v.db"
            record = mb.parse_page(nuxt_script(devalue(MATCHBOX)), DETAIL_URL)[0]
            totals = mb.export_staging(db, [record])
            self.assertEqual(totals["posts_written"], 1)
            self.assertEqual(totals["releases_written"], 0)
            conn = sqlite3.connect(db)
            stats = mb.stats(db)
            conn.close()
            self.assertEqual(stats["metadata_only_posts"], 1)
            self.assertEqual(stats["direct_links"], 0)
            self.assertEqual(stats["sources_active"], 0,
                             "a trailer must never be counted as an active stream")

    def test_verify_never_touches_a_trailer(self):
        """The verify command probes sources; with no sources it must make no call."""
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "v.db"
            record = mb.parse_page(nuxt_script(devalue(MATCHBOX)), DETAIL_URL)[0]
            mb.export_staging(db, [record])
            with silenced(), mock.patch.object(mb, "http_head") as head:
                totals = mb.verify_sources(db_path=db, delay=0)
            self.assertEqual(head.call_count, 0)
            self.assertEqual(totals["checked"], 0)


class CliTests(unittest.TestCase):
    def test_harvest_is_reachable_from_the_command_line(self):
        args = mb.parse_args(["harvest", "--pages", "3", "--per-page", "20",
                              "--limit", "5"])
        self.assertEqual(args.command, "harvest")
        self.assertEqual((args.pages, args.per_page, args.limit), (3, 20, 5))

    def test_sync_defaults_are_bounded(self):
        args = mb.parse_args(["sync"])
        self.assertEqual(args.pages, mb.API_MAX_PAGES)
        self.assertEqual(args.per_page, mb.API_PAGE_SIZE)

    def test_politeness_defaults_hold_the_floor(self):
        self.assertLessEqual(mb.DEFAULT_WORKERS, 2)
        self.assertGreaterEqual(mb.DEFAULT_DELAY, 0.3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
