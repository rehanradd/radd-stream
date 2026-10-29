#!/usr/bin/env python3
"""Offline unit tests for import_themoviebox.py (no network, no real vault).

Run with:  python3 -S Fast_Fetch/tests/test_themoviebox_import.py

The Nuxt payloads here are hand-authored `devalue` flat pools — the exact array
shape Nuxt writes into ``<script id="__NUXT_DATA__">`` — rather than values
produced by this module's own writer, so the unflattener is checked against the
format instead of against itself.
"""

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import fast_fetch  # noqa: E402
from importers import import_themoviebox as im  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def render(pool) -> str:
    return ('<html><head><script type="application/json" '
            'id="__NUXT_DATA__">' + json.dumps(pool) + "</script></head></html>")


#: One movie, three quality variants. Indices are literal devalue slots.
MOVIE_POOL = [
    {"data": 1},                                              # 0
    {"movie": 2},                                             # 1
    {"title": 3, "releaseDate": 4, "duration": 5, "genre": 6,  # 2
     "poster": 7, "blurHash": 8, "avgHueLight": 9, "avgHueDark": 10,
     "media": 11, "isPornographic": 12, "dubs": 13, "cast": 14},
    "Neon Horizon",                                           # 3
    "2024-03-01",                                             # 4
    "2h 14m",                                                 # 5
    [15, 16],                                                 # 6
    "https://pbcdnw.aoneroom.com/posters/neon-horizon.jpg",   # 7
    "LKO2blurhash",                                           # 8
    "#d1b28f",                                                # 9
    "#2a1f14",                                                # 10
    [17, 18, 19],                                             # 11
    False,                                                    # 12
    [20, 21],                                                 # 13
    [22, 23],                                                 # 14
    "Action",                                                 # 15
    "Sci-Fi",                                                 # 16
    "https://macdn.aoneroom.com/media/neon-horizon-ld.mp4",   # 17
    "https://macdn.aoneroom.com/media/neon-horizon-sd.mp4",   # 18
    "https://macdn.aoneroom.com/media/neon-horizon-hd.mp4",   # 19
    "English",                                                # 20
    "Hindi",                                                  # 21
    "Ana Voss",                                               # 22
    "Leo Marlowe",                                            # 23
]

SERIES_POOL = [
    {"data": 1},                                              # 0
    {"series": 2},                                            # 1
    {"title": 3, "seasons": 4, "releaseDate": 5},             # 2
    "Hollow Signal",                                          # 3
    [6],                                                      # 4
    "2023-09-10",                                             # 5
    {"seasonNumber": 7, "episodes": 8},                       # 6
    1,                                                        # 7
    [9, 10],                                                  # 8
    {"episodeNumber": 11, "title": 12, "media": 13},          # 9
    {"episodeNumber": 14, "title": 15, "media": 16},          # 10
    1, "Cold Open", [17],                                     # 11,12,13
    2, "Static", [18],                                        # 14,15,16
    "https://macdn.aoneroom.com/media/hollow-s01e01-hd.mp4",  # 17
    "https://macdn.aoneroom.com/media/hollow-s01e02-sd.mp4",  # 18
]

MOVIE_URL = "https://themoviebox.xyz/movie/neon-horizon"
SERIES_URL = "https://themoviebox.xyz/series/hollow-signal"


def movie_record():
    return im.parse_page(render(MOVIE_POOL), MOVIE_URL)[0]


def _db(path):
    conn = sqlite3.connect(path)
    im.ensure_schema(conn)
    conn.commit()
    return conn


def _queue(conn, *locs):
    conn.executemany(
        "INSERT OR IGNORE INTO sitemap_cache (loc, lastmod, slug, scraped,"
        " raw_json, error_count) VALUES (?, '2024-01-01', ?, 0, '{}', 0)",
        [(loc, loc.rsplit("/", 1)[-1]) for loc in locs])
    conn.commit()


def _reset_crawl_state():
    im.STOP_REQUESTED = False
    im._RATE_LIMITED.clear()
    im._LAST_START[0] = 0.0


# ---------------------------------------------------------------------------
# 1. devalue unflattening
# ---------------------------------------------------------------------------

class UnflattenTests(unittest.TestCase):
    def test_hand_authored_pool_hydrates_exactly(self):
        data = im.unflatten(MOVIE_POOL)
        movie = data["data"]["movie"]
        self.assertEqual(movie["title"], "Neon Horizon")
        self.assertEqual(movie["genre"], ["Action", "Sci-Fi"])
        self.assertEqual(movie["dubs"], ["English", "Hindi"])
        self.assertEqual(movie["cast"], ["Ana Voss", "Leo Marlowe"])
        self.assertIs(movie["isPornographic"], False)
        self.assertEqual(len(movie["media"]), 3)
        self.assertTrue(movie["media"][2].endswith("-hd.mp4"))

    def test_shared_reference_hydrates_to_the_same_object(self):
        # Both keys reference the same slot, so they must share one object.
        pool = [{"a": 1, "b": 1}, {"x": 2}, "shared"]
        data = im.unflatten(pool)
        self.assertIs(data["a"], data["b"])
        self.assertEqual(data["a"]["x"], "shared")

    def test_number_at_a_slot_is_a_literal_not_an_index(self):
        # Only container members are indices. A number sitting at a slot is
        # its plain value — including a negative one.
        data = im.unflatten([{"n": 1, "m": 2}, -1, 7])
        self.assertEqual((data["n"], data["m"]), (-1, 7))

    def test_plain_json_object_passes_through(self):
        self.assertEqual(im.unflatten({"a": 1}), {"a": 1})

    def test_undefined_and_hole_are_handled(self):
        # "-1" as a *member* is devalue's undefined; "-2" inside the array is a
        # hole, which the reader drops rather than exposing a sentinel.
        pool = [{"a": 1, "b": -1, "arr": 2}, "value", [-2, 1]]
        data = im.unflatten(pool)
        self.assertIsNone(data["b"])
        self.assertEqual(data["a"], "value")
        self.assertEqual(data["arr"], ["value"])

    def test_typed_date_slot(self):
        pool = [{"when": 1}, ["Date", "2024-03-01T00:00:00Z"]]
        self.assertEqual(im.unflatten(pool)["when"], "2024-03-01T00:00:00Z")

    def test_out_of_range_and_literal_scalars(self):
        pool = [{"n": 1, "s": 2, "f": 3}, 42, "text", 1.5]
        data = im.unflatten(pool)
        self.assertEqual((data["n"], data["s"], data["f"]), (42, "text", 1.5))


class ExtractPayloadTests(unittest.TestCase):
    def test_absent_script_returns_none(self):
        self.assertIsNone(im.extract_nuxt_payload("<html>no nuxt</html>"))

    def test_invalid_json_returns_none(self):
        html = '<script id="__NUXT_DATA__">{not json}</script>'
        self.assertIsNone(im.extract_nuxt_payload(html))

    def test_attributes_before_id_are_tolerated(self):
        html = ('<script type="application/json" data-ssr="true" '
                'id="__NUXT_DATA__">[{"a":1},"x"]</script>')
        self.assertEqual(im.extract_nuxt_payload(html)["a"], "x")


# ---------------------------------------------------------------------------
# 2. movie parsing
# ---------------------------------------------------------------------------

class ParseMovieTests(unittest.TestCase):
    def test_identity_and_metadata(self):
        rec = movie_record()
        self.assertEqual(rec["title"], "Neon Horizon")
        self.assertEqual(rec["clean_title"], "Neon Horizon")
        self.assertEqual(rec["year"], 2024)
        self.assertEqual(rec["media_type"], "movie")
        self.assertEqual(rec["genres"], "Action, Sci-Fi")
        self.assertEqual(rec["languages"], "English, Hindi")
        self.assertEqual(rec["cast_names"], "Ana Voss, Leo Marlowe")
        self.assertEqual(rec["duration"], "2h 14m")
        self.assertEqual(rec["release_date"], "2024-03-01")
        self.assertEqual(rec["source_site"], "themoviebox")
        self.assertEqual(rec["poster_url"],
                         "https://pbcdnw.aoneroom.com/posters/neon-horizon.jpg")
        self.assertEqual(rec["raw_meta"]["blurHash"], "LKO2blurhash")
        self.assertEqual(rec["raw_meta"]["avgHueLight"], "#d1b28f")
        self.assertEqual(rec["raw_meta"]["avgHueDark"], "#2a1f14")
        self.assertEqual(rec["canonical_key"],
                         fast_fetch.generate_canonical_key("Neon Horizon", 2024))

    def test_three_quality_releases_each_with_one_direct_tier1_source(self):
        rec = movie_record()
        self.assertEqual(len(rec["releases"]), 3)
        qualities = [r["quality"] for r in rec["releases"]]
        self.assertEqual(qualities, ["LD", "SD", "HD"])
        for release in rec["releases"]:
            self.assertEqual(len(release["sources"]), 1)
            src = release["sources"][0]
            self.assertEqual(src["service"], "themoviebox")
            self.assertEqual(src["service_tier"], 1)
            self.assertEqual(src["playback_type"], "direct")
            self.assertEqual(src["status"], "active")
            self.assertEqual(src["is_temporary"], 0)
            self.assertEqual(src["mime_type"], "video/mp4")
            self.assertTrue(src["final_url"].endswith(".mp4"))
            self.assertEqual(src["source_url"], src["final_url"])
            self.assertEqual(src["resource_id"],
                             src["final_url"].rsplit("/", 1)[-1])

    def test_quality_token_comes_from_the_url(self):
        self.assertEqual(im._quality_from_url("https://x/a-ld.mp4"), "LD")
        self.assertEqual(im._quality_from_url("https://x/a-sd.mp4"), "SD")
        self.assertEqual(im._quality_from_url("https://x/a-hd.mp4"), "HD")
        self.assertEqual(im._quality_from_url("https://x/a-1080p.mp4"), "1080p")
        self.assertIsNone(im._quality_from_url("https://x/a.mp4"))

    def test_non_cdn_video_urls_are_dropped(self):
        pool = [{"m": 1}, {"title": 2, "media": 3}, "Film",
                ["https://ads.example/trailer.mp4",
                 "https://macdn.aoneroom.com/media/film-hd.mp4"]]
        rec = im.parse_page(render(pool), "https://themoviebox.xyz/movie/film")[0]
        urls = [s["final_url"] for r in rec["releases"] for s in r["sources"]]
        self.assertEqual(urls, ["https://macdn.aoneroom.com/media/film-hd.mp4"])

    def test_a_page_without_media_is_not_a_record(self):
        pool = [{"d": 1}, {"title": 2}, "Film"]
        self.assertEqual(im.parse_page(render(pool), MOVIE_URL), [])

    def test_a_page_without_nuxt_is_not_a_record(self):
        self.assertEqual(im.parse_page("<html><body>hi</body></html>", MOVIE_URL), [])


# ---------------------------------------------------------------------------
# 3. series parsing
# ---------------------------------------------------------------------------

class ParseSeriesTests(unittest.TestCase):
    def test_one_work_many_episode_releases(self):
        records = im.parse_page(render(SERIES_POOL), SERIES_URL)
        self.assertEqual(len(records), 1)
        rec = records[0]
        self.assertEqual(rec["title"], "Hollow Signal")
        self.assertEqual(rec["year"], 2023)
        self.assertEqual(rec["media_type"], "series")
        self.assertEqual(json.loads(rec["seasons"]), [1])
        self.assertEqual(len(rec["releases"]), 2)
        by_ep = {r["episode"]: r for r in rec["releases"]}
        self.assertEqual(set(by_ep), {1, 2})
        self.assertEqual(by_ep[1]["season"], 1)
        self.assertEqual(by_ep[1]["quality"], "HD")
        self.assertIn("Cold Open", by_ep[1]["label"])
        self.assertIn("S01E01", by_ep[1]["label"])
        self.assertEqual(by_ep[2]["quality"], "SD")
        self.assertIn("Static", by_ep[2]["label"])


# ---------------------------------------------------------------------------
# 4. adult flagging
# ---------------------------------------------------------------------------

class AdultFlagTests(unittest.TestCase):
    def _record(self, item_extra, url=MOVIE_URL, title="Some Film"):
        pool = [{"d": 1}, dict({"title": 2, "media": 3}, **item_extra), title,
                "https://macdn.aoneroom.com/media/some-hd.mp4"]
        return im.parse_page(render(pool), url)[0]

    def test_is_pornographic_flag(self):
        pool = [{"d": 1}, {"title": 2, "media": 3, "isPornographic": 4},
                "Clean Looking", "https://macdn.aoneroom.com/media/a-hd.mp4", True]
        rec = im.parse_page(render(pool), MOVIE_URL)[0]
        self.assertEqual(rec["is_18_plus"], 1)

    def test_web_high_risk_flag(self):
        pool = [{"d": 1}, {"title": 2, "media": 3, "webHighRisk": 4},
                "Clean Looking", "https://macdn.aoneroom.com/media/a-hd.mp4", True]
        self.assertEqual(im.parse_page(render(pool), MOVIE_URL)[0]["is_18_plus"], 1)

    def test_web_midnight_path(self):
        rec = self._record({}, url="https://themoviebox.xyz/web/midnight/film",
                           title="Clean Looking")
        self.assertEqual(rec["is_18_plus"], 1)

    def test_adult_title_vocabulary(self):
        rec = self._record({}, title="Adult Diary")
        self.assertEqual(rec["is_18_plus"], 1)

    def test_clean_title_stays_unflagged(self):
        self.assertEqual(movie_record()["is_18_plus"], 0)

    def test_flags_are_recorded_in_raw_meta(self):
        pool = [{"d": 1}, {"title": 2, "media": 3, "webHighRisk": 4},
                "Film", "https://macdn.aoneroom.com/media/a-hd.mp4", True]
        rec = im.parse_page(render(pool), MOVIE_URL)[0]
        self.assertTrue(rec["raw_meta"]["webHighRisk"])


# ---------------------------------------------------------------------------
# 5. staging export + merge compatibility + isolation
# ---------------------------------------------------------------------------

class ExportTests(unittest.TestCase):
    def test_export_writes_posts_releases_sources(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "themoviebox.db"
            totals = im.export_staging(db, [movie_record()])
            self.assertEqual(totals["posts_written"], 1)
            self.assertEqual(totals["releases_written"], 3)
            self.assertEqual(totals["sources_written"], 3)
            self.assertEqual(im.stats(db)["works"], 1)
            self.assertEqual(im.stats(db)["releases"], 3)
            self.assertEqual(im.stats(db)["direct_links"], 3)
            self.assertEqual(im.stats(db)["tier1_links"], 3)

    def test_source_columns_are_persisted(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "themoviebox.db"
            im.export_staging(db, [movie_record()])
            conn = sqlite3.connect(db)
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM sources ORDER BY id LIMIT 1").fetchone()
            conn.close()
            self.assertEqual(row["service"], "themoviebox")
            self.assertEqual(row["service_tier"], 1)
            self.assertEqual(row["playback_type"], "direct")
            self.assertEqual(row["status"], "active")
            self.assertEqual(row["is_temporary"], 0)
            self.assertEqual(row["mime_type"], "video/mp4")
            self.assertEqual(row["quality"], "LD")

    def test_re_export_replaces_and_does_not_duplicate(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "themoviebox.db"
            im.export_staging(db, [movie_record()])
            im.export_staging(db, [movie_record()])
            self.assertEqual(im.stats(db)["releases"], 3)
            self.assertEqual(im.stats(db)["direct_links"], 3)
            # A re-export of the same work (same title + year) with a different
            # variant set replaces the old one instead of accumulating.
            pool = [{"m": 1}, {"title": 2, "releaseDate": 3, "media": 4},
                    "Neon Horizon", "2024-03-01",
                    "https://macdn.aoneroom.com/media/neon-horizon-4k.mp4"]
            changed = im.parse_page(render(pool), MOVIE_URL)
            im.export_staging(db, changed)
            self.assertEqual(im.stats(db)["direct_links"], 1)

    def test_a_record_without_a_key_is_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "themoviebox.db"
            totals = im.export_staging(db, [{"clean_title": "No Key"}])
            self.assertEqual(totals["skipped"], 1)

    def test_merge_reads_the_staging_vault(self):
        import merge_catalogs
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "themoviebox.db"
            im.export_staging(db, [movie_record()])
            conn = sqlite3.connect(db)
            conn.row_factory = sqlite3.Row
            try:
                self.assertEqual(merge_catalogs._source_family(conn), "staging")
                post = conn.execute("SELECT * FROM posts").fetchone()
                collected = merge_catalogs._collect_staging_post(conn, post)
            finally:
                conn.close()
            self.assertEqual(collected["clean_title"], "Neon Horizon")
            self.assertEqual(collected["source_site"], "themoviebox")
            self.assertEqual(collected["content_type"], "movie")
            sources = [s for r in collected["releases"] for s in r["sources"]]
            self.assertEqual(len(sources), 3)
            self.assertTrue(all(s["service"] == "themoviebox" for s in sources))
            self.assertTrue(all(s["playback_type"] == "direct" for s in sources))

    def test_default_vault_is_isolated_from_production(self):
        self.assertEqual(im.DEFAULT_DB_PATH.name, "themoviebox.db")
        self.assertIn("radd-stream-data", str(im.DEFAULT_DB_PATH))
        self.assertNotIn("fast_fetch.db", str(im.DEFAULT_DB_PATH))
        self.assertNotIn("/opt/radd-stream", str(im.DEFAULT_DB_PATH))


# ---------------------------------------------------------------------------
# 6. sync (discovery)
# ---------------------------------------------------------------------------

SITEMAP = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    "<url><loc>https://themoviebox.xyz/movie/neon-horizon</loc>"
    "<lastmod>2024-03-01</lastmod></url>"
    "<url><loc>https://themoviebox.xyz/series/hollow-signal</loc></url>"
    "</urlset>"
)

SITEMAP_INDEX = (
    '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    "<sitemap><loc>https://themoviebox.xyz/sitemap-movies.xml</loc></sitemap>"
    "</sitemapindex>"
)


class SyncTests(unittest.TestCase):
    def test_urlset_is_queued(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "themoviebox.db"
            with mock.patch.object(im, "http_get",
                                   return_value=(200, im.BASE_URL + "/sitemap.xml",
                                                 SITEMAP)):
                totals = im.sync_catalog(db, verbose=False)
            self.assertEqual(totals["queued"], 2)
            self.assertEqual(im.stats(db)["sitemap_rows"], 2)
            conn = sqlite3.connect(db)
            row = conn.execute(
                "SELECT lastmod FROM sitemap_cache WHERE loc = ?",
                ("https://themoviebox.xyz/movie/neon-horizon",)).fetchone()
            conn.close()
            self.assertEqual(row[0], "2024-03-01")

    def test_duplicates_are_not_requeued(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "themoviebox.db"
            with mock.patch.object(im, "http_get",
                                   return_value=(200, im.BASE_URL, SITEMAP)):
                im.sync_catalog(db, verbose=False)
                totals = im.sync_catalog(db, verbose=False)
            self.assertEqual(totals["queued"], 0)
            self.assertEqual(totals["duplicates"], 2)

    def test_sitemap_index_recurses_into_children(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "themoviebox.db"

            def fake(url, **kwargs):
                if url.endswith("sitemap.xml"):
                    return 200, url, SITEMAP_INDEX
                return 200, url, SITEMAP

            with mock.patch.object(im, "http_get", side_effect=fake):
                totals = im.sync_catalog(db, verbose=False)
            self.assertEqual(totals["sitemaps"], 2)
            self.assertEqual(totals["queued"], 2)

    def test_seeds_are_queued_even_without_a_sitemap(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "themoviebox.db"
            with mock.patch.object(im, "http_get", return_value=(404, im.BASE_URL, "")):
                totals = im.sync_catalog(
                    db, seeds=["https://themoviebox.xyz/movie/manual"], verbose=False)
            self.assertEqual(totals["queued"], 1)
            self.assertEqual(totals["errors"], 1)

    def test_missing_sitemap_is_an_error_not_a_crash(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "themoviebox.db"
            with mock.patch.object(im, "http_get", return_value=(0, im.BASE_URL, "")):
                totals = im.sync_catalog(db, verbose=False)
            self.assertEqual(totals["queued"], 0)
            self.assertEqual(totals["errors"], 1)


# ---------------------------------------------------------------------------
# 7. crawl
# ---------------------------------------------------------------------------

class CrawlTests(unittest.TestCase):
    def setUp(self):
        _reset_crawl_state()

    def tearDown(self):
        _reset_crawl_state()

    def _mock_get(self, pages_by_url):
        def fake(url, **kwargs):
            body = pages_by_url.get(url)
            if body is None:
                return 404, url, ""
            if isinstance(body, int):
                return body, url, ""
            return 200, url, body
        return fake

    def test_a_good_page_lands_in_the_vault_and_is_marked(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "themoviebox.db"
            conn = _db(db)
            _queue(conn, MOVIE_URL)
            conn.close()
            with mock.patch.object(im, "memory_ok", return_value=(True, "ok")), \
                    mock.patch.object(im, "http_get",
                                      side_effect=self._mock_get({MOVIE_URL: render(MOVIE_POOL)})):
                totals = im.crawl_pending(db_path=db, workers=1, delay=0,
                                          verbose=False)
            self.assertEqual(totals["posts"], 1)
            self.assertEqual(totals["sources"], 3)
            self.assertEqual(im.stats(db)["works"], 1)
            conn = sqlite3.connect(db)
            state = conn.execute("SELECT scraped FROM sitemap_cache WHERE loc = ?",
                                 (MOVIE_URL,)).fetchone()[0]
            conn.close()
            self.assertEqual(state, 1)

    def test_429_pauses_and_leaves_the_row_queued(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "themoviebox.db"
            conn = _db(db)
            _queue(conn, MOVIE_URL)
            conn.close()
            with mock.patch.object(im, "memory_ok", return_value=(True, "ok")), \
                    mock.patch.object(im, "http_get", return_value=(429, MOVIE_URL, "")):
                totals = im.crawl_pending(db_path=db, workers=1, delay=0,
                                          verbose=False)
            self.assertTrue(totals["paused_rate_limit"])
            conn = sqlite3.connect(db)
            state = conn.execute("SELECT scraped FROM sitemap_cache WHERE loc = ?",
                                 (MOVIE_URL,)).fetchone()[0]
            conn.close()
            self.assertEqual(state, 0)

    def test_a_404_is_parked_and_never_retried(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "themoviebox.db"
            conn = _db(db)
            _queue(conn, MOVIE_URL)
            conn.close()
            with mock.patch.object(im, "memory_ok", return_value=(True, "ok")), \
                    mock.patch.object(im, "http_get", return_value=(404, MOVIE_URL, "")):
                totals = im.crawl_pending(db_path=db, workers=1, delay=0,
                                          verbose=False)
            self.assertEqual(totals["parked"], 1)
            self.assertEqual(im.stats(db)["parked"], 1)
            conn = sqlite3.connect(db)
            state = conn.execute("SELECT scraped FROM sitemap_cache WHERE loc = ?",
                                 (MOVIE_URL,)).fetchone()[0]
            conn.close()
            self.assertEqual(state, -1)
            # A second crawl finds nothing pending.
            with mock.patch.object(im, "memory_ok", return_value=(True, "ok")):
                again = im.crawl_pending(db_path=db, workers=1, delay=0, verbose=False)
            self.assertEqual(again["pages"], 0)

    def test_linkless_page_is_retryable(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "themoviebox.db"
            conn = _db(db)
            _queue(conn, MOVIE_URL)
            conn.close()
            with mock.patch.object(im, "memory_ok", return_value=(True, "ok")), \
                    mock.patch.object(im, "http_get",
                                      return_value=(200, MOVIE_URL, "<html>no nuxt</html>")):
                totals = im.crawl_pending(db_path=db, workers=1, delay=0,
                                          verbose=False)
            self.assertEqual(totals["no_playable"], 1)
            conn = sqlite3.connect(db)
            row = conn.execute("SELECT scraped, error_count FROM sitemap_cache"
                               " WHERE loc = ?", (MOVIE_URL,)).fetchone()
            conn.close()
            self.assertEqual(row[0], 2)  # retryable
            self.assertEqual(row[1], 1)

    def test_two_workers_crawl_every_queued_page(self):
        other = "https://themoviebox.xyz/movie/second"
        pool = [{"m": 1}, {"title": 2, "media": 3}, "Second Film",
                "https://macdn.aoneroom.com/media/second-hd.mp4"]
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "themoviebox.db"
            conn = _db(db)
            _queue(conn, MOVIE_URL, other)
            conn.close()
            pages = {MOVIE_URL: render(MOVIE_POOL), other: render(pool)}
            with mock.patch.object(im, "memory_ok", return_value=(True, "ok")), \
                    mock.patch.object(im, "http_get",
                                      side_effect=self._mock_get(pages)):
                totals = im.crawl_pending(db_path=db, workers=2, delay=0,
                                          verbose=False)
            self.assertEqual(totals["pages"], 2)
            self.assertEqual(im.stats(db)["works"], 2)

    def test_refuses_to_start_below_the_memory_floor(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "themoviebox.db"
            conn = _db(db)
            _queue(conn, MOVIE_URL)
            conn.close()
            with mock.patch.object(im, "memory_ok",
                                   return_value=(False, "MemAvailable 10 MB")):
                totals = im.crawl_pending(db_path=db, workers=1, delay=0,
                                          verbose=False)
            self.assertTrue(totals["stopped_for_memory"])
            self.assertEqual(im.stats(db)["sitemap_rows"], 1)

    def test_workers_are_clamped(self):
        self.assertEqual(im._clamp_workers(0), 1)
        self.assertEqual(im._clamp_workers(2), 2)
        self.assertEqual(im._clamp_workers(999), im.MAX_WORKERS)


# ---------------------------------------------------------------------------
# 8. verify
# ---------------------------------------------------------------------------

class VerifyTests(unittest.TestCase):
    def setUp(self):
        _reset_crawl_state()

    def test_head_probe_marks_active_and_dead(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "themoviebox.db"
            im.export_staging(db, [movie_record()])
            # Force one source back to unverified so both states are exercised.
            conn = sqlite3.connect(db)
            conn.execute("UPDATE sources SET status = 'unverified'"
                         " WHERE final_url LIKE '%-ld.mp4'")
            conn.commit()
            conn.close()

            def fake_head(url, timeout=0):
                if url.endswith("-ld.mp4"):
                    return 200
                if url.endswith("-sd.mp4"):
                    return 404
                return 0  # transport failure -> unknown

            with mock.patch.object(im, "http_head", side_effect=fake_head):
                totals = im.verify_sources(db_path=db, delay=0, verbose=False)
            self.assertEqual(totals["active"], 1)
            self.assertEqual(totals["dead"], 1)
            self.assertEqual(totals["unknown"], 1)
            conn = sqlite3.connect(db)
            states = dict(conn.execute(
                "SELECT final_url, status FROM sources").fetchall())
            conn.close()
            self.assertEqual(states["https://macdn.aoneroom.com/media/neon-horizon-sd.mp4"],
                             "dead")

    def test_limit_caps_the_probe_set(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "themoviebox.db"
            im.export_staging(db, [movie_record()])
            with mock.patch.object(im, "http_head", return_value=200) as head:
                totals = im.verify_sources(db_path=db, limit=1, delay=0,
                                           verbose=False)
            self.assertEqual(totals["checked"], 1)
            self.assertEqual(head.call_count, 1)


# ---------------------------------------------------------------------------
# 9. CLI + politeness defaults
# ---------------------------------------------------------------------------

class CliTests(unittest.TestCase):
    def test_defaults_are_polite(self):
        self.assertEqual(im.DEFAULT_WORKERS, 2)
        self.assertAlmostEqual(im.DEFAULT_DELAY, 0.3)
        args = im.parse_args(["crawl"])
        self.assertEqual(args.workers, 2)
        self.assertAlmostEqual(args.delay, 0.3)
        self.assertEqual(args.batch_size, im.BATCH_SIZE)

    def test_all_four_commands_parse(self):
        for command in ("sync", "crawl", "verify", "stats"):
            args = im.parse_args([command])
            self.assertEqual(args.command, command)
            self.assertEqual(args.db, str(im.DEFAULT_DB_PATH))

    def test_sync_seed_is_repeatable(self):
        args = im.parse_args(["sync", "--seed", "https://a", "--seed", "https://b"])
        self.assertEqual(args.seed, ["https://a", "https://b"])

    def test_stats_command_prints_json_and_returns_zero(self):
        with tempfile.TemporaryDirectory() as td:
            db = str(Path(td) / "themoviebox.db")
            im.export_staging(db, [movie_record()])
            with mock.patch("sys.stdout", new_callable=lambda: _Sink()) as out:
                code = im.main(["stats", "--db", db])
            self.assertEqual(code, 0)
            self.assertIn('"works": 1', out.text)


class _Sink:
    def __init__(self):
        self.text = ""

    def write(self, chunk):
        self.text += chunk

    def flush(self):
        pass


if __name__ == "__main__":
    unittest.main(verbosity=2)
