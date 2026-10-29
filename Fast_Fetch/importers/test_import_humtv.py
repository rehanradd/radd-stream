#!/usr/bin/env python3
"""Offline unit tests for import_humtv.py (no network, no real vault)."""

import json
import re
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import fast_fetch
from importers import import_humtv as hv


def _page(title, iframes, poster="https://hum.tv/wp-content/uploads/p.jpg"):
    tags = "".join(f'<iframe src="{src}" allowfullscreen></iframe>' for src in iframes)
    return (
        "<html><head>"
        f'<meta property="og:title" content="{title}" />'
        f'<meta property="og:image" content="{poster}" />'
        f"</head><body>{tags}</body></html>"
    )


def _db(path):
    conn = sqlite3.connect(path)
    hv.ensure_schema(conn)
    conn.commit()
    return conn


def _queue(conn, *locs, lastmod="2024-05-06T10:00:00"):
    conn.executemany(
        "INSERT INTO sitemap_cache (loc, lastmod, slug, scraped, raw_json, error_count)"
        " VALUES (?, ?, ?, 0, '{}', 0)",
        [(loc, lastmod, loc.rstrip("/").rsplit("/", 1)[-1]) for loc in locs])
    conn.commit()


class ParseTitleTests(unittest.TestCase):
    def test_plain_episode_title(self):
        parsed = hv.parse_title("Meesni – Episode 01", "meesni-episode-01")
        self.assertEqual(parsed, {"title": "Meesni", "season": None, "episode": 1})

    def test_season_and_episode_in_the_title(self):
        parsed = hv.parse_title(
            "Sultan Salahuddin Ayyubi – S1 – Episode 12",
            "sultan-salahuddin-ayyubi-s1-episode-12")
        self.assertEqual(parsed["title"], "Sultan Salahuddin Ayyubi")
        self.assertEqual((parsed["season"], parsed["episode"]), (1, 12))

    def test_dash_after_the_word_episode(self):
        parsed = hv.parse_title("Aakhir Kab Tak Episode – 01",
                                "aakhir-kab-tak-episode-01")
        self.assertEqual(parsed, {"title": "Aakhir Kab Tak", "season": None,
                                  "episode": 1})

    def test_season_falls_back_to_the_slug(self):
        parsed = hv.parse_title("Ishq Murshid Episode 07",
                                "ishq-murshid-s2-episode-07")
        self.assertEqual(parsed["title"], "Ishq Murshid")
        self.assertEqual(parsed["episode"], 7)
        self.assertEqual(parsed["season"], 2)

    def test_a_feature_page_keeps_its_whole_title(self):
        parsed = hv.parse_title("Kaisi Teri Khudgharzi – Hum TV", "kaisi-teri-khudgharzi")
        self.assertEqual(parsed, {"title": "Kaisi Teri Khudgharzi",
                                  "season": None, "episode": None})


class ParsePageTests(unittest.TestCase):
    LOC = "https://hum.tv/meesni-episode-01/"
    YEAR = 2024

    def test_embed_url_and_watch_url_variants(self):
        for src in ("https://www.youtube.com/embed/abcDEF12345",
                    "https://youtu.be/abcDEF12345&#038;embed=true",
                    "https://www.youtube.com/watch?v=abcDEF12345&t=3"):
            record = hv.parse_page(_page("Meesni – Episode 01", [src]),
                                   self.LOC, self.YEAR)
            self.assertIsNotNone(record, src)
            source = record["releases"][0]["sources"][0]
            self.assertEqual(source["resource_id"], "abcDEF12345")
            self.assertEqual(source["source_url"],
                             "https://www.youtube.com/watch?v=abcDEF12345")
            self.assertEqual(source["service"], "youtube")
            self.assertEqual(source["playback_type"], "iframe")
            self.assertEqual(source["status"], "unverified")

    def test_one_release_per_episode_page_and_no_download_mirror(self):
        record = hv.parse_page(_page("Meesni – Episode 01", [
            "https://www.youtube.com/embed/abcDEF12345"]), self.LOC, self.YEAR)
        self.assertEqual(len(record["releases"]), 1)
        release = record["releases"][0]
        self.assertEqual((release["season"], release["episode"]), (None, 1))
        self.assertEqual(release["label"], "Meesni Episode 01")
        self.assertEqual(record["canonical_key"],
                         fast_fetch.generate_canonical_key("Meesni", self.YEAR))
        self.assertEqual(record["year"], self.YEAR)
        self.assertEqual(record["source_site"] if "source_site" in record else "humtv",
                         "humtv")
        self.assertIsNone(release["quality"])

    def test_wordpress_entity_dash_in_og_title_still_splits_the_episode(self):
        record = hv.parse_page(_page("Hurmat &#8211; Episode 06", [
            "https://youtu.be/DTyP7i3CYq4?si=x&#038;embed=true"]),
            "https://hum.tv/hurmat-episode-06/", 2026)
        self.assertEqual(record["title"], "Hurmat")
        self.assertEqual(record["releases"][0]["episode"], 6)
        self.assertEqual(record["releases"][0]["label"], "Hurmat Episode 06")
        self.assertEqual(record["releases"][0]["sources"][0]["resource_id"],
                         "DTyP7i3CYq4")

    def test_a_page_without_a_player_is_not_a_work(self):
        self.assertIsNone(hv.parse_page(_page("Meesni – Episode 01", []),
                                        self.LOC, self.YEAR))

    def test_the_adult_flag_comes_from_fast_fetch_not_a_local_list(self):
        with mock.patch.object(hv.fast_fetch, "is_adult_title", return_value=1) as spy:
            record = hv.parse_page(_page("Meesni – Episode 01", [
                "https://www.youtube.com/embed/abcDEF12345"]), self.LOC, self.YEAR)
        self.assertEqual(record["is_18_plus"], 1)
        spy.assert_called_once_with("Meesni", "meesni-episode-01")

    def test_no_local_adult_or_rating_vocabulary(self):
        source = Path(hv.__file__).read_text().lower()
        for banned in ("unrated", "uncut", "adult_keywords", "adult_patterns"):
            self.assertNotIn(banned, source)


class SyncTests(unittest.TestCase):
    def test_rest_pages_are_read_into_the_queue(self):
        pages = {
            1: [{"date": "2024-03-01T10:00:00", "slug": "a-episode-01",
                 "link": "https://hum.tv/a-episode-01/", "title": {"rendered": "A"}},
                {"date": "2023-11-02T10:00:00", "slug": "b-episode-02",
                 "link": "https://hum.tv/b-episode-02/", "title": {"rendered": "B"}}],
            2: [{"date": "2022-01-05T10:00:00", "slug": "c",
                 "link": "https://hum.tv/c/", "title": {"rendered": "C"}}],
        }

        def fake_get(url, timeout=0, retries=0, debug=None):
            if "per_page=1&" in url:
                return 200, url, "[]"
            page = int(re.search(r"[?&]page=(\d+)", url).group(1))
            return 200, url, json.dumps(pages.get(page, []))

        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "humtv_staging.db"
            with mock.patch.object(hv, "http_get", side_effect=fake_get):
                totals = hv.sync_catalog(db, verbose=False)
            self.assertEqual(totals["inserted"], 3)
            self.assertEqual(totals["errors"], 0)
            conn = sqlite3.connect(db)
            rows = conn.execute(
                "SELECT loc, lastmod, scraped FROM sitemap_cache ORDER BY loc").fetchall()
            conn.close()
            self.assertEqual(len(rows), 3)
            self.assertEqual(rows[0], ("https://hum.tv/a-episode-01/",
                                       "2024-03-01T10:00:00", 0))


class ExportTests(unittest.TestCase):
    def test_re_exporting_a_page_replaces_its_release_and_source(self):
        def record(video_id):
            return hv.parse_page(_page("Meesni – Episode 01", [
                f"https://www.youtube.com/embed/{video_id}"]),
                "https://hum.tv/meesni-episode-01/", 2024)

        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "humtv_staging.db"
            first = hv.export_staging(db, [record("abcDEF12345")])
            second = hv.export_staging(db, [record("zzzYYY98765")])
            self.assertEqual((first["posts_written"], first["sources_written"]), (1, 1))
            self.assertEqual((second["posts_written"], second["sources_written"]), (1, 1))
            conn = sqlite3.connect(db)
            counts = conn.execute(
                "SELECT (SELECT COUNT(*) FROM posts),"
                " (SELECT COUNT(*) FROM releases),"
                " (SELECT COUNT(*) FROM sources),"        # noqa: E501
                " (SELECT resource_id FROM sources)").fetchone()
            conn.close()
            self.assertEqual(counts, (1, 1, 1, "zzzYYY98765"))

    def test_stats_report_the_five_fleet_numbers(self):
        rec = hv.parse_page(_page("Meesni – Episode 01", [
            "https://www.youtube.com/embed/abcDEF12345"]),
            "https://hum.tv/meesni-episode-01/", 2024)
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "humtv_staging.db"
            hv.export_staging(db, [rec])
            conn = _db(db)
            _queue(conn, "https://hum.tv/other/")
            conn.close()
            got = hv.stats(db)
        self.assertEqual(got["works"], 1)
        self.assertEqual(got["releases"], 1)
        self.assertEqual(got["watch_links"], 1)
        self.assertEqual(got["download_links"], 0)
        self.assertEqual(got["sources_unverified"], 1)
        self.assertEqual((got["sources_active"], got["sources_dead"]), (0, 0))
        self.assertEqual(got["queued"], 1)


class MemoryTests(unittest.TestCase):
    def test_both_floors_are_enforced(self):
        healthy = ("MemTotal: 8000000 kB\nMemAvailable: 3805600 kB\n"
                   "SwapTotal: 2000000 kB\nSwapFree: 1581956 kB\n")
        self.assertTrue(hv.memory_ok(healthy)[0])
        low_mem = "MemAvailable: 2499000 kB\nSwapFree: 1581956 kB\n"
        self.assertFalse(hv.memory_ok(low_mem)[0])
        low_swap = "MemAvailable: 3805600 kB\nSwapFree: 819000 kB\n"
        self.assertFalse(hv.memory_ok(low_swap)[0])

    def test_a_low_floor_stops_the_crawl_before_the_first_request(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "humtv_staging.db"
            conn = _db(db)
            _queue(conn, "https://hum.tv/a-episode-01/")
            conn.close()
            with mock.patch.object(hv, "http_get",
                                   side_effect=AssertionError("must not fetch")), \
                    mock.patch.object(hv, "memory_ok",
                                      return_value=(False, "MemAvailable 100 MB")):
                totals = hv.crawl_pending(db_path=db, delay=0, verbose=False)
            self.assertTrue(totals["stopped_for_memory"])
            self.assertEqual(totals["pages"], 0)


class SeriesIdentityTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(hv, "memory_ok", return_value=(True, "test"))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_series_base_strips_season_and_episode(self):
        self.assertEqual(hv.series_base("ishq-murshid-s2-episode-07"), "ishq-murshid")
        self.assertEqual(hv.series_base("hurmat-episode-06"), "hurmat")
        self.assertEqual(hv.series_base("hurmat-ost"), "hurmat-ost")

    def test_the_earliest_year_wins_for_a_series(self):
        rows = [
            {"loc": "https://hum.tv/ishq-murshid-episode-01/",
             "slug": "ishq-murshid-episode-01", "lastmod": "2024-01-02T00:00:00"},
            {"loc": "https://hum.tv/ishq-murshid-episode-40/",
             "slug": "ishq-murshid-episode-40", "lastmod": "2023-12-20T00:00:00"},
        ]
        self.assertEqual(hv.series_year_map(rows), {"ishq-murshid": 2023})

    def test_a_series_that_crosses_new_year_stays_one_work(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "humtv_staging.db"
            conn = _db(db)
            conn.executemany(
                "INSERT INTO sitemap_cache (loc, lastmod, slug, scraped, raw_json,"
                " error_count) VALUES (?, ?, ?, 0, '{}', 0)",
                [("https://hum.tv/ishq-murshid-episode-40/",
                  "2023-12-20T00:00:00", "ishq-murshid-episode-40"),
                 ("https://hum.tv/ishq-murshid-episode-41/",
                  "2024-01-02T00:00:00", "ishq-murshid-episode-41")])
            conn.commit()
            conn.close()

            def fake_get(url, timeout=0, retries=0, debug=None):
                episode = 40 if "40" in url else 41
                return 200, url, _page(f"Ishq Murshid – Episode {episode}", [
                    f"https://www.youtube.com/embed/vid{episode:08d}"])

            with mock.patch.object(hv, "http_get", side_effect=fake_get):
                hv.crawl_pending(db_path=db, delay=0, verbose=False)
            conn = sqlite3.connect(db)
            posts = conn.execute(
                "SELECT canonical_key, year FROM posts").fetchall()
            releases = conn.execute(
                "SELECT post_canonical_key, episode_number FROM releases"
                " ORDER BY episode_number").fetchall()
            conn.close()
            self.assertEqual(posts, [("ishq-murshid_2023", 2023)])
            self.assertEqual(releases, [("ishq-murshid_2023", 40),
                                        ("ishq-murshid_2023", 41)])


class CrawlTests(unittest.TestCase):
    LOC = "https://hum.tv/meesni-episode-01/"

    def setUp(self):
        # The memory floor is checked in its own test; these tests must not
        # depend on how busy the host happens to be.
        patcher = mock.patch.object(hv, "memory_ok", return_value=(True, "test"))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_429_pauses_the_queue_and_leaves_rows_untouched(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "humtv_staging.db"
            conn = _db(db)
            _queue(conn, self.LOC, "https://hum.tv/second-episode-02/")
            conn.close()
            with mock.patch.object(hv, "http_get",
                                   return_value=(429, self.LOC, "")):
                totals = hv.crawl_pending(db_path=db, delay=0, verbose=False)
            self.assertTrue(totals["paused_rate_limit"])
            self.assertEqual(totals["pages"], 1)
            conn = sqlite3.connect(db)
            pending = conn.execute(
                "SELECT COUNT(*) FROM sitemap_cache WHERE scraped = 0").fetchone()[0]
            conn.close()
            self.assertEqual(pending, 2)
            hv._RATE_LIMITED.clear()

    def test_a_404_is_parked_with_its_ledger_and_a_linkless_page_is_retryable(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "humtv_staging.db"
            conn = _db(db)
            _queue(conn, self.LOC, "https://hum.tv/no-player/")
            conn.close()

            def fake_get(url, timeout=0, retries=0, debug=None):
                if url.endswith("no-player/"):
                    return 200, url, _page("Meesni – Episode 02", [])
                return 404, url, ""

            with mock.patch.object(hv, "http_get", side_effect=fake_get):
                totals = hv.crawl_pending(db_path=db, delay=0, verbose=False)
            self.assertEqual(totals["parked"], 1)
            self.assertEqual(totals["no_playable"], 1)
            self.assertEqual(totals["failed_rows"], 2)
            conn = sqlite3.connect(db)
            states = dict(conn.execute(
                "SELECT loc, scraped FROM sitemap_cache").fetchall())
            conn.close()
            self.assertEqual(states[self.LOC], 1)
            self.assertEqual(states["https://hum.tv/no-player/"], 2)

    def test_a_clean_page_lands_in_the_vault_and_is_marked_scraped(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "humtv_staging.db"
            conn = _db(db)
            _queue(conn, self.LOC)
            conn.close()
            body = _page("Meesni – Episode 01",
                         ["https://www.youtube.com/embed/abcDEF12345"])
            with mock.patch.object(hv, "http_get", return_value=(200, self.LOC, body)):
                totals = hv.crawl_pending(db_path=db, delay=0, verbose=False)
            self.assertEqual(
                (totals["pages"], totals["posts"], totals["releases"],
                 totals["sources"]), (1, 1, 1, 1))
            got = hv.stats(db)
            self.assertEqual(got["queued"], 0)
            self.assertEqual(got["crawled"], 1)
            self.assertEqual(got["works"], 1)


class VerifyTests(unittest.TestCase):
    def test_oembed_marks_active_and_dead_and_never_follows_a_file(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "humtv_staging.db"
            hv.export_staging(db, [
                hv.parse_page(_page("Meesni – Episode 01", [
                    "https://www.youtube.com/embed/abcDEF12345"]),
                    "https://hum.tv/meesni-episode-01/", 2024),
                hv.parse_page(_page("Meesni – Episode 02", [
                    "https://www.youtube.com/embed/zzzYYY98765"]),
                    "https://hum.tv/meesni-episode-02/", 2024),
            ])
            seen = []

            def fake_get(url, timeout=0, retries=0, debug=None):
                seen.append(url)
                if "zzzYYY98765" in url:
                    return 404, url, ""
                return 200, url, '{"author_name": "HUM TV"}'

            with mock.patch.object(hv, "http_get", side_effect=fake_get):
                totals = hv.verify_sources(db_path=db, delay=0, verbose=False)
            self.assertEqual((totals["active"], totals["dead"]), (1, 1))
            self.assertTrue(all(u.startswith(hv.YOUTUBE_OEMBED) for u in seen))
            got = hv.stats(db)
            self.assertEqual((got["sources_active"], got["sources_dead"]), (1, 1))
            self.assertEqual(got["sources_unverified"], 0)


if __name__ == "__main__":
    unittest.main()
