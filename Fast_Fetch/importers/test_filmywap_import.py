#!/usr/bin/env python3
"""
test_filmywap_import.py — offline unit tests for the Filmywap staging importer.

No test touches the network: the socket is replaced with a raiser for the whole
module and every reader runs against fixtures shaped from pages measured on
2026-10-29. The rules kept here:

* only `/movie/<slug>` URLs from the sitemap become candidates;
* the schema.org block is the metadata source, and a page without one is parked,
  never invented;
* a series is episode-addressable: every `seasons[].episodes[]` entry becomes its
  own releases, and an episode whose API call failed is recorded as a gap;
* signed MP4 URLs are stored `is_temporary = 1` and `unverified`, with the durable
  `/api/stream` URL kept in `bridge_url` — this importer claims no probe.
"""

from __future__ import annotations

import contextlib
import io
import json
import socket
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import import_filmywap as fw  # noqa: E402


class _NoLiveSocket:
    def __init__(self, *args, **kwargs):
        raise AssertionError("offline suite attempted a live connection")


socket.socket = _NoLiveSocket  # type: ignore[attr-defined]


@contextlib.contextmanager
def silenced():
    buf = io.StringIO()
    with contextlib.ExitStack() as stack:
        for stream in ("stdout", "stderr"):
            stack.enter_context(mock.patch.object(sys, stream, buf))
        yield buf


MOVIE_SLUG = "runner-hindi-Qmo94ivMnY5"
MOVIE_URL = f"https://filmywap.site/movie/{MOVIE_SLUG}"
SERIES_SLUG = "dr-house-C5lmFzu3Ph6"
SERIES_URL = f"https://filmywap.site/movie/{SERIES_SLUG}"
POSTER = "https://pbcdnw.aoneroom.com/image/2026/09/24/ded94.png"
MP4_1080 = ("https://bcdnxw.hakunaymatata.com/vegamovies/96e6.mp4"
            "?sign=b1bfc5791e91c1129e6c5464bd821e6b&t=1793219650")
MP4_480 = ("https://bcdnxw.hakunaymatata.com/vegamovies/d552.mp4"
           "?sign=aaa&t=1793219651")

SITEMAP = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://filmywap.site/</loc><lastmod>2026-10-28</lastmod></url>
  <url><loc>https://filmywap.site/movies</loc></url>
  <url><loc>{MOVIE_URL}</loc><lastmod>2026-10-27</lastmod></url>
  <url><loc>{MOVIE_URL}</loc><lastmod>2026-10-27</lastmod></url>
  <url><loc>{SERIES_URL}</loc></url>
  <url><loc>https://filmywap.site/genre/action</loc></url>
  <url><loc>https://filmywap.site/watch/{MOVIE_SLUG}</loc></url>
</urlset>"""


def ld_movie(**overrides) -> dict:
    block = {
        "@context": "https://schema.org",
        "@type": "Movie",
        "name": "Runner [Hindi]",
        "url": MOVIE_URL,
        "description": "A former soldier races to save a little girl.",
        "inLanguage": "en",
        "image": POSTER,
        "datePublished": "2026-09-11",
        "genre": ["Action", "Comedy", "Thriller"],
        "aggregateRating": {"@type": "AggregateRating", "ratingValue": "6.6"},
        "actor": [{"@type": "Person", "name": "Alan Ritchson"},
                  {"@type": "Person", "name": "Owen Wilson"}],
        "countryOfOrigin": {"@type": "Country", "name": "Australia"},
    }
    block.update(overrides)
    return block


def ld_series(**overrides) -> dict:
    block = {
        "@context": "https://schema.org",
        "@type": "TVSeries",
        "name": "Dr. House S1-S8",
        "url": SERIES_URL,
        "description": "An antisocial maverick doctor solves puzzling cases.",
        "inLanguage": "en",
        "image": POSTER,
        "datePublished": "2004-11-16",
        "genre": ["Drama"],
        "aggregateRating": {"@type": "AggregateRating", "ratingValue": "8.7"},
        "actor": [{"@type": "Person", "name": "Greg Yaitanes"}],
        "countryOfOrigin": {"@type": "Country", "name": "United States"},
    }
    block.update(overrides)
    return block


def page(ld: dict | None = ld_movie(), extra: str = "") -> str:
    blocks = []
    if ld is not None:
        blocks.append(json.dumps(ld))
    breadcrumb = {"@context": "https://schema.org", "@type": "BreadcrumbList",
                  "itemListElement": [{"@type": "ListItem", "position": 1,
                                       "name": "Home", "item": fw.BASE_URL}]}
    blocks.append(json.dumps(breadcrumb))
    return ("<html><head>"
            + "".join(f'<script type="application/ld+json">{b}</script>'
                      for b in blocks)
            + f"</head><body>{extra}</body></html>")


def source(res: int, url: str = MP4_1080, size: int = 1000) -> dict:
    return {"id": f"id-{res}", "resolution": res, "format": "MP4", "url": url,
            "size": size, "duration": 5911, "codec": "h264"}


def movie_stream(**overrides) -> dict:
    payload = {
        "subjectId": "5013914659406102880",
        "detailPath": MOVIE_SLUG,
        "hasResource": True,
        "isSeries": False,
        "allowDownload": True,
        "vipLocked": False,
        "limited": False,
        "freeNum": 999,
        "captions": [],
        "sources": [source(1080, MP4_1080, 2280985815),
                    source(480, MP4_480, 932697897),
                    source(360, MP4_480, 378680813)],
    }
    payload.update(overrides)
    return payload


def series_stream(**overrides) -> dict:
    payload = {
        "subjectId": "5277074313408040752",
        "detailPath": SERIES_SLUG,
        "hasResource": True,
        "isSeries": True,
        "allowDownload": True,
        "vipLocked": False,
        "limited": False,
        "freeNum": 999,
        "captions": [],
        "seasons": [
            {"se": 1, "episodes": [1, 2]},
            {"se": 2, "episodes": [1]},
        ],
        "sources": [source(1080), source(720), source(480), source(360)],
    }
    payload.update(overrides)
    return payload


class SitemapTests(unittest.TestCase):
    def test_only_movie_urls_and_deduped(self):
        rows = fw.parse_sitemap(SITEMAP)
        self.assertEqual([loc for loc, _ in rows], [MOVIE_URL, SERIES_URL])

    def test_lastmod_is_kept(self):
        rows = dict(fw.parse_sitemap(SITEMAP))
        self.assertEqual(rows[MOVIE_URL], "2026-10-27")
        self.assertIsNone(rows[SERIES_URL])

    def test_slug_validation(self):
        self.assertEqual(fw.slug_from(MOVIE_URL), MOVIE_SLUG)
        self.assertEqual(fw.slug_from("https://filmywap.site/movies"), "")
        self.assertEqual(fw.slug_from("https://evil.example/movie/x"), "")


class JsonLdTests(unittest.TestCase):
    def test_picks_movie_and_ignores_breadcrumb(self):
        ld = fw.parse_jsonld(page(ld_movie()))
        self.assertEqual(ld["@type"], "Movie")
        self.assertEqual(ld["name"], "Runner [Hindi]")

    def test_graph_is_supported(self):
        wrapped = page(None, extra="") + (
            '<script type="application/ld+json">'
            + json.dumps({"@graph": [ld_series()]}) + "</script>")
        self.assertEqual(fw.parse_jsonld(wrapped)["@type"], "TVSeries")

    def test_missing_block_returns_none(self):
        self.assertIsNone(fw.parse_jsonld(page(None)))

    def test_broken_json_is_skipped(self):
        html = '<script type="application/ld+json">{not json</script>'
        self.assertIsNone(fw.parse_jsonld(html))


class FieldTests(unittest.TestCase):
    def test_languages_from_title_tag_and_schema(self):
        self.assertEqual(fw.languages_for("Runner [Hindi]", "en"),
                         ["Hindi", "English"])
        self.assertEqual(fw.languages_for("Movie [Dual Audio]", "hi"),
                         ["Dual Audio", "Hindi"])

    def test_unknown_bracket_tag_is_not_a_language(self):
        self.assertEqual(fw.languages_for("Movie [2026] [Hindi]", None), ["Hindi"])

    def test_year_and_duration(self):
        self.assertEqual(fw.year_of("2026-09-11"), 2026)
        self.assertEqual(fw.duration_text(5911), "01:38:31")
        self.assertEqual(fw.duration_text(90), "01:30")
        self.assertIsNone(fw.duration_text(None))

    def test_stream_url_shape(self):
        self.assertEqual(fw.stream_api_url(MOVIE_SLUG),
                         f"https://filmywap.site/api/stream?slug={MOVIE_SLUG}")
        self.assertTrue(fw.stream_api_url(SERIES_SLUG, 2, 5).endswith("&se=2&ep=5"))

    def test_signed_expiry_is_read(self):
        self.assertEqual(fw._expiry(MP4_1080), 1793219650)
        self.assertIsNone(fw._expiry("https://host/x.mp4"))


class ReleaseTests(unittest.TestCase):
    def test_movie_releases_are_signed_and_unverified(self):
        releases = fw.releases_from_stream(movie_stream(), "Runner [Hindi]", MOVIE_URL)
        self.assertEqual([r["quality"] for r in releases], ["1080p", "480p", "360p"])
        for rel in releases:
            src = rel["sources"][0]
            self.assertEqual(src["is_temporary"], 1)
            self.assertEqual(src["status"], "unverified")
            self.assertEqual(src["playback_type"], "download")
            self.assertEqual(src["service"], "bcdnxw.hakunaymatata.com")
            self.assertIsNone(src["last_checked"])
            self.assertTrue(rel["bridge_url"].startswith(fw.BASE_URL + "/api/stream"))

    def test_episode_labels_and_numbers(self):
        releases = fw.releases_from_stream(
            series_stream(), "Dr. House S1-S8", SERIES_URL, season=2, episode=5)
        self.assertTrue(releases[0]["label"].startswith("Dr. House S1-S8 S02E05"))
        self.assertEqual(releases[0]["season_number"], 2)
        self.assertEqual(releases[0]["episode_number"], 5)
        self.assertTrue(releases[0]["bridge_url"].endswith("&se=2&ep=5"))

    def test_source_without_url_is_dropped(self):
        payload = movie_stream(sources=[{"id": "x", "resolution": 1080}])
        self.assertEqual(fw.releases_from_stream(payload, "T", MOVIE_URL), [])


class BuildRecordTests(unittest.TestCase):
    def test_movie_record_fields(self):
        record = fw.build_record(MOVIE_URL, page(ld_movie()), movie_stream())
        self.assertEqual(record["canonical_key"], MOVIE_SLUG)
        self.assertEqual(record["title"], "Runner [Hindi]")
        self.assertEqual(record["media_type"], "movie")
        self.assertEqual(record["year"], 2026)
        self.assertEqual(record["imdb_rating"], "6.6")
        self.assertEqual(record["country"], "Australia")
        self.assertEqual(json.loads(record["genres"]), ["Action", "Comedy", "Thriller"])
        self.assertEqual(json.loads(record["languages"]), ["Hindi", "English"])
        self.assertEqual(record["duration"], "01:38:31")
        self.assertEqual(len(record["releases"]), 3)
        self.assertEqual(record["raw_meta"]["subject_id"], "5013914659406102880")
        self.assertEqual(record["raw_meta"]["episodes_without_stream"], [])
        self.assertIsNone(record["seasons"])

    def test_series_record_expands_episodes(self):
        episodes = {(1, 2): series_stream(), (2, 1): series_stream()}
        record = fw.build_record(SERIES_URL, page(ld_series()),
                                 series_stream(), episodes)
        self.assertEqual(record["media_type"], "series")
        self.assertEqual(json.loads(record["seasons"]), [1, 2])
        # (1,1) from the first call + (1,2) + (2,1), four resolutions each.
        self.assertEqual(len(record["releases"]), 12)
        self.assertEqual(record["raw_meta"]["episodes_without_stream"], [])

    def test_missing_episode_is_a_gap_not_an_invention(self):
        record = fw.build_record(SERIES_URL, page(ld_series()),
                                 series_stream(), {(1, 2): series_stream()})
        # Only 1x1 and 1x2 resolved; 2x1 is recorded as missing.
        self.assertEqual(len(record["releases"]), 8)
        self.assertEqual(record["raw_meta"]["episodes_without_stream"],
                         ["se2ep1:missing"])

    def test_no_jsonld_returns_none(self):
        self.assertIsNone(fw.build_record(MOVIE_URL, page(None), movie_stream()))

    def test_unlinked_title_is_still_a_record(self):
        record = fw.build_record(MOVIE_URL, page(ld_movie()),
                                 movie_stream(sources=[], hasResource=False))
        self.assertIsNotNone(record)
        self.assertEqual(record["releases"], [])
        self.assertFalse(record["raw_meta"]["has_resource"])

    def test_adult_and_animated_flags(self):
        adult = fw.build_record(MOVIE_URL, page(ld_movie(name="XXX Adult Show")),
                                movie_stream())
        self.assertEqual(adult["is_18_plus"], 1)
        cartoon = fw.build_record(MOVIE_URL, page(ld_movie(genre=["Animation"])),
                                  movie_stream())
        self.assertEqual(cartoon["is_animated"], 1)
        self.assertEqual(cartoon["is_18_plus"], 0)

    def test_measured_adult_slugs_are_flagged(self):
        # Slugs counted in the live sitemap on 2026-10-29.
        for title in ("Married Stepsis F-cked", "MILF with Huge Clitoris",
                      "Sister in Law F-cked", "Bahu F-cked by Horny Sasur",
                      "Generation Porn"):
            record = fw.build_record(MOVIE_URL, page(ld_movie(name=title)),
                                     movie_stream())
            self.assertEqual(record["is_18_plus"], 1, title)
        mainstream = fw.build_record(MOVIE_URL, page(ld_movie(name="Runner [Hindi]")),
                                     movie_stream())
        self.assertEqual(mainstream["is_18_plus"], 0)

    def test_slug_is_the_canonical_key(self):
        record = fw.build_record(MOVIE_URL, page(ld_movie()), movie_stream())
        for rel in record["releases"]:
            self.assertEqual(record["slug"], MOVIE_SLUG)


class StagingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db = Path(self.tmp.name)

    def tearDown(self):
        self.db.unlink(missing_ok=True)

    def record(self):
        return fw.build_record(MOVIE_URL, page(ld_movie()), movie_stream())

    def test_export_writes_rows_and_marks_cache(self):
        result = fw.export_staging(self.db, [self.record()])
        self.assertEqual(result["posts_written"], 1)
        self.assertEqual(result["releases_written"], 3)
        self.assertEqual(result["sources_written"], 3)
        conn = sqlite3.connect(self.db)
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0], 1)
            self.assertEqual(conn.execute(
                "SELECT scraped FROM sitemap_cache WHERE loc = ?", (MOVIE_URL,)
            ).fetchone()[0], 1)
            self.assertEqual(conn.execute(
                "SELECT COUNT(*) FROM sources WHERE status = 'active'").fetchone()[0], 0)
            self.assertEqual(conn.execute(
                "SELECT COUNT(*) FROM sources WHERE is_temporary = 1").fetchone()[0], 3)
        finally:
            conn.close()

    def test_re_export_replaces_releases_without_duplicating(self):
        fw.export_staging(self.db, [self.record()])
        fw.export_staging(self.db, [self.record()])
        conn = sqlite3.connect(self.db)
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM releases").fetchone()[0], 3)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0], 3)
        finally:
            conn.close()

    def test_stats_counts(self):
        fw.export_staging(self.db, [self.record()])
        got = fw.stats(self.db)
        self.assertEqual(got["posts"], 1)
        self.assertEqual(got["releases"], 3)
        self.assertEqual(got["temporary_sources"], 3)
        self.assertEqual(got["active_sources"], 0)


class FailureLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db = Path(self.tmp.name)
        conn = sqlite3.connect(self.db)
        fw.ensure_schema(conn)
        conn.close()

    def tearDown(self):
        self.db.unlink(missing_ok=True)

    def queue(self, loc, scraped=0, errors=0, raw="{}"):
        conn = sqlite3.connect(self.db)
        conn.execute(
            "INSERT OR REPLACE INTO sitemap_cache (loc, lastmod, slug, scraped, "
            "raw_json, error_count) VALUES (?, NULL, ?, ?, ?, ?);",
            (loc, fw.slug_from(loc), scraped, raw, errors))
        conn.commit()
        conn.close()

    def test_retry_then_cap_is_dead_with_reason(self):
        self.queue(MOVIE_URL)
        with silenced():
            for _ in range(fw.MAX_SCRAPE_ATTEMPTS):
                fw._bump_error(self.db, MOVIE_URL, fw._failure("http-500", 500,
                                                               MOVIE_URL, "http-500"))
        conn = sqlite3.connect(self.db)
        try:
            scraped, errors, raw = conn.execute(
                "SELECT scraped, error_count, raw_json FROM sitemap_cache "
                "WHERE loc = ?", (MOVIE_URL,)).fetchone()
        finally:
            conn.close()
        payload = json.loads(raw)
        self.assertEqual(scraped, -1)
        self.assertEqual(errors, 3)
        self.assertEqual(payload["status"], "dead")
        self.assertEqual(len(payload["failures"]), 3)
        self.assertEqual(payload["failures"][-1]["http_status"], 500)

    def test_parked_below_cap_stays_eligible(self):
        self.queue(MOVIE_URL, scraped=2, errors=1)
        conn = sqlite3.connect(self.db)
        try:
            rows = conn.execute(
                fw.PENDING_SELECT,
                (*fw.QUEUED_SCRAPE_STATES, fw.MAX_SCRAPE_ATTEMPTS)).fetchall()
        finally:
            conn.close()
        self.assertEqual([r[0] for r in rows], [MOVIE_URL])

    def test_parked_at_cap_is_not_selected(self):
        self.queue(MOVIE_URL, scraped=-1, errors=3)
        conn = sqlite3.connect(self.db)
        try:
            rows = conn.execute(
                fw.PENDING_SELECT,
                (*fw.QUEUED_SCRAPE_STATES, fw.MAX_SCRAPE_ATTEMPTS)).fetchall()
        finally:
            conn.close()
        self.assertEqual(rows, [])

    def test_missing_jsonld_is_parked_with_kind(self):
        self.queue(MOVIE_URL)
        html = page(None)
        with silenced(), mock.patch.object(
                fw, "http_get", return_value=(200, MOVIE_URL, html, {})):
            fw.crawl_pending(db_path=self.db)
        conn = sqlite3.connect(self.db)
        try:
            scraped, raw = conn.execute(
                "SELECT scraped, raw_json FROM sitemap_cache WHERE loc = ?",
                (MOVIE_URL,)).fetchone()
        finally:
            conn.close()
        self.assertEqual(scraped, 2)
        self.assertEqual(json.loads(raw)["failures"][-1]["kind"], "no-jsonld")


class CrawlTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db = Path(self.tmp.name)
        conn = sqlite3.connect(self.db)
        fw.ensure_schema(conn)
        conn.execute(
            "INSERT INTO sitemap_cache (loc, lastmod, slug, scraped, raw_json, "
            "error_count) VALUES (?, NULL, ?, 0, '{}', 0);",
            (MOVIE_URL, MOVIE_SLUG))
        conn.commit()
        conn.close()
        fw.STOP_REQUESTED = False

    def tearDown(self):
        fw.STOP_REQUESTED = False
        self.db.unlink(missing_ok=True)

    def test_crawl_writes_a_movie(self):
        with silenced(), mock.patch.object(
                fw, "http_get", return_value=(200, MOVIE_URL, page(ld_movie()), {})), \
                mock.patch.object(fw, "fetch_stream",
                                  return_value=(movie_stream(), "")):
            totals = fw.crawl_pending(db_path=self.db, delay=0)
        self.assertEqual(totals["posts"], 1)
        self.assertEqual(totals["releases"], 3)
        self.assertEqual(totals["sources"], 3)

    def test_crawl_records_api_failure(self):
        with silenced(), mock.patch.object(
                fw, "http_get", return_value=(200, MOVIE_URL, page(ld_movie()), {})), \
                mock.patch.object(fw, "fetch_stream",
                                  return_value=(None, "api-http-500")):
            totals = fw.crawl_pending(db_path=self.db, delay=0)
        self.assertEqual(totals["posts"], 0)
        self.assertEqual(totals["failed_rows"], 1)
        self.assertEqual(totals["parked"], 0)

    def test_stop_signal_spends_no_attempt(self):
        fw.STOP_REQUESTED = True
        with silenced(), mock.patch.object(fw, "http_get") as get:
            totals = fw.crawl_pending(db_path=self.db, delay=0)
        self.assertEqual(get.call_count, 0)
        self.assertEqual(totals["posts"], 0)
        conn = sqlite3.connect(self.db)
        try:
            scraped, errors = conn.execute(
                "SELECT scraped, error_count FROM sitemap_cache WHERE loc = ?",
                (MOVIE_URL,)).fetchone()
        finally:
            conn.close()
        self.assertEqual((scraped, errors), (0, 0))

    def test_a_429_pauses_the_crawl_without_burning_the_queue(self):
        second = "https://filmywap.site/movie/second-movie-2025"
        conn = sqlite3.connect(self.db)
        conn.execute(
            "INSERT INTO sitemap_cache (loc, lastmod, slug, scraped, raw_json, "
            "error_count) VALUES (?, NULL, ?, 0, '{}', 0);",
            (second, "second-movie-2025"))
        conn.commit()
        conn.close()
        with silenced(), mock.patch.object(
                fw, "http_get", return_value=(429, MOVIE_URL, "", {})) as get:
            totals = fw.crawl_pending(db_path=self.db, delay=0)
        self.assertTrue(totals["paused_rate_limit"])
        self.assertEqual(get.call_count, 1, "the crawl must stop on the first 429")
        conn = sqlite3.connect(self.db)
        try:
            states = dict(conn.execute(
                "SELECT loc, scraped FROM sitemap_cache").fetchall())
        finally:
            conn.close()
        self.assertEqual(states[MOVIE_URL], 2)
        self.assertEqual(states[second], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
