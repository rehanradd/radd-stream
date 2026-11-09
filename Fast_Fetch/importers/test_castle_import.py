#!/usr/bin/env python3
"""
test_castle_import.py — offline unit tests for the Castle (bulwik.com) importer.

No test touches the network: every fetch/probe is a fake and every fixture
is shaped from pages measured live on this host on 2026-11-10 (the probe
run in the batch-1 checkpoint). The rules this suite keeps, and the measured
fact each one exists because of:

* the signed .m3u8 is JSON-escaped in the page (``\\u0026`` for ``&``) and
  must be unescaped before use — a truncated URL (no expire param) 403s.
* the signature lives ~3h from minting, and the page itself may be
  CDN-cached with an already-expired signature: a URL minted ~13h before
  its page fetch 403d while a fresh one 200d with a real #EXTM3U. So a
  signature already expired at scrape time is stored ``unverified``,
  never ``active``; the stored URL is always ``is_temporary=1`` and the
  resolver re-extracts a fresh signature on every press.
* a movie page ships JSON-LD Movie (name, image, description, genre,
  datePublished, duration PT123M, contentRating). Series season pages
  carry only ONE signed .m3u8 in static HTML with episodes 2+ behind JS,
  so this batch is movies only — the enumerator walks
  /movies/sitemap/N.xml and skips anything else.
"""

from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import import_castle as ct  # noqa: E402

MOVIES_SITEMAP_1 = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://www.bulwik.com/movie/all-pass/10285268178004214</loc></url>
<url><loc>https://www.bulwik.com/movie/7-star-boys/10285162770131208</loc></url>
<url><loc>https://www.bulwik.com/movie/meesaya-murukku/6689645106300928</loc></url>
</urlset>"""

MOVIES_SITEMAP_2 = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://www.bulwik.com/movie/scene/10270907647639352</loc></url>
<url><loc>https://www.bulwik.com/series/marshals-season-2/10290779789781498</loc></url>
</urlset>"""

# expire=1893456000000 -> 2030-01-01, safely in the future for the test.
MOVIE_HTML = """<!DOCTYPE html><html><head>
<title>All Pass Full Movie Watch Online Free</title>
<script type="application/ld+json">{"@context":"https://schema.org","@graph":[{"@type":"Movie","@id":"https://www.bulwik.com/movie/all-pass/10285268178004214","name":"All Pass","image":"https://img1.bhcxy.com/image/2daffdb21745b63ab6b4769d8052b350fa0d753c.jpg","url":"https://www.bulwik.com/movie/all-pass/10285268178004214","description":"Three families in North Chennai share peaceful lives.","genre":["Drama"],"datePublished":"2026-10-09","duration":"PT123M","contentRating":"PG","inLanguage":"en-IN"}]}</script>
</head><body>
<video><source src="https://img01.tlnob.com/video/30a719e0b2063f6666445411191bb26c2be59d31/index_401.m3u8?auth_key=n2W309DOxzOumDaP%2FwlhF3eC9U%2FWdODY93ycfLmbH04%3D\\u0026expire=1893456000000"></video>
</body></html>"""

MOVIE_HTML_STALE = MOVIE_HTML.replace("expire=1893456000000",
                                      "expire=1000000000000")

MOVIE_HTML_NO_STREAM = """<!DOCTYPE html><html><head>
<title>Scene Full Movie Watch Online Free</title>
<script type="application/ld+json">{"@context":"https://schema.org","@graph":[{"@type":"Movie","name":"Scene","image":"https://img1.bhcxy.com/image/abc.jpg","description":"A film.","genre":["Thriller"],"datePublished":"2024-05-01","duration":"PT90M","contentRating":"PG"}]}</script>
</head><body><p>No player on this page.</p></body></html>"""


def probe_ok(url):
    return {"ok": True, "status": 200, "is_playlist": True}


def probe_fail(url):
    return {"ok": False, "status": 403, "is_playlist": False}


class TestUnescapeAndDuration(unittest.TestCase):
    def test_u0026_becomes_ampersand(self):
        self.assertEqual(
            ct.unescape_page_url(
                "https://img01.tlnob.com/video/abc/index_401.m3u8"
                "?auth_key=XYZ%3D\\u0026expire=1893456000000"),
            "https://img01.tlnob.com/video/abc/index_401.m3u8"
            "?auth_key=XYZ%3D&expire=1893456000000")

    def test_duration_pt123m_is_123(self):
        self.assertEqual(ct.parse_duration_iso("PT123M"), 123)
        self.assertEqual(ct.parse_duration_iso("PT1H30M"), 90)
        self.assertEqual(ct.parse_duration_iso("PT2H"), 120)
        self.assertIsNone(ct.parse_duration_iso("123"))
        self.assertIsNone(ct.parse_duration_iso(None))


class TestParseMoviePage(unittest.TestCase):
    def _page(self, html=MOVIE_HTML):
        return ct.parse_movie_page(
            html, "https://www.bulwik.com/movie/all-pass/10285268178004214")

    def test_json_ld_movie_fields(self):
        page = self._page()
        self.assertEqual(page["title"], "All Pass")
        self.assertEqual(page["year"], 2026)
        self.assertEqual(page["genres"], "Drama")
        self.assertEqual(page["duration"], "123")
        self.assertEqual(page["poster_url"],
                         "https://img1.bhcxy.com/image/2daffdb21745b63ab6b4769d8052b350fa0d753c.jpg")
        self.assertEqual(page["content_rating"], "PG")
        self.assertIn("North Chennai", page["synopsis"])
        self.assertEqual(page["is_18_plus"], 0)

    def test_signed_url_unescaped_with_expire(self):
        page = self._page()
        self.assertEqual(
            page["signed_url"],
            "https://img01.tlnob.com/video/30a719e0b2063f6666445411191bb26c2be59d31/"
            "index_401.m3u8?auth_key=n2W309DOxzOumDaP%2FwlhF3eC9U%2FWdODY93ycfLmbH04%3D"
            "&expire=1893456000000")
        self.assertEqual(page["expire_ms"], 1893456000000)
        self.assertFalse(page["stale"])

    def test_expired_signature_is_stale(self):
        page = ct.parse_movie_page(
            MOVIE_HTML_STALE,
            "https://www.bulwik.com/movie/all-pass/10285268178004214")
        self.assertTrue(page["stale"])
        self.assertEqual(page["expire_ms"], 1000000000000)

    def test_non_movie_url_is_none(self):
        self.assertIsNone(ct.parse_movie_page(
            MOVIE_HTML, "https://www.bulwik.com/series/x/1"))
        self.assertIsNone(ct.parse_movie_page(MOVIE_HTML, "https://www.bulwik.com/"))

    def test_adult_rating_flags(self):
        html = MOVIE_HTML.replace('"contentRating":"PG"', '"contentRating":"18+"')
        page = ct.parse_movie_page(
            html, "https://www.bulwik.com/movie/all-pass/10285268178004214")
        self.assertEqual(page["is_18_plus"], 1)


class TestBuildRecord(unittest.TestCase):
    def _page(self, html=MOVIE_HTML):
        return ct.parse_movie_page(
            html, "https://www.bulwik.com/movie/all-pass/10285268178004214")

    def test_fresh_probed_is_active_and_temporary(self):
        record = ct.build_record(self._page(), probe=probe_ok)
        self.assertEqual(record["canonical_key"], "castle-all-pass")
        self.assertEqual(record["media_type"], "movie")
        self.assertEqual(record["year"], 2026)
        src = record["releases"][0]["sources"][0]
        self.assertEqual(src["status"], "active")
        self.assertEqual(src["is_temporary"], 1)
        self.assertEqual(src["playback_type"], "direct")
        self.assertIn("expire=1893456000000", src["final_url"])
        self.assertEqual(src["source_url"],
                         "https://www.bulwik.com/movie/all-pass/10285268178004214")

    def test_stale_signature_is_unverified_without_probing(self):
        calls = []

        def counting_probe(url):
            calls.append(url)
            return probe_ok(url)

        record = ct.build_record(
            ct.parse_movie_page(
                MOVIE_HTML_STALE,
                "https://www.bulwik.com/movie/all-pass/10285268178004214"),
            probe=counting_probe)
        self.assertEqual(record["releases"][0]["sources"][0]["status"],
                         "unverified")
        self.assertEqual(calls, [])

    def test_probe_failure_is_unverified(self):
        record = ct.build_record(self._page(), probe=probe_fail)
        self.assertEqual(record["releases"][0]["sources"][0]["status"],
                         "unverified")

    def test_no_signed_stream_stages_nothing(self):
        page = ct.parse_movie_page(
            MOVIE_HTML_NO_STREAM,
            "https://www.bulwik.com/movie/scene/10270907647639352")
        self.assertIsNotNone(page)
        self.assertIsNone(ct.build_record(page, probe=probe_ok))


class TestExportAndSync(unittest.TestCase):
    def _tmp_db(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        return tmp.name

    def test_export_round_trip(self):
        db = self._tmp_db()
        page = ct.parse_movie_page(
            MOVIE_HTML,
            "https://www.bulwik.com/movie/all-pass/10285268178004214")
        record = ct.build_record(page, probe=probe_ok)
        totals = ct.export_staging(db, posts=[record])
        self.assertEqual((totals["posts_written"], totals["releases_written"],
                          totals["sources_written"]), (1, 1, 1))
        ok, result = ct.verify_db(db)
        self.assertTrue(ok)
        self.assertEqual(result["sources_active"], 1)
        conn = sqlite3.connect(db)
        row = conn.execute(
            "SELECT is_temporary, status FROM sources").fetchone()
        self.assertEqual(row, (1, "active"))
        conn.close()

    def test_sync_walks_movie_sitemaps_in_order_and_skips_series(self):
        db = self._tmp_db()

        def fake_fetch(url):
            if "movies/sitemap/1.xml" in url:
                return (200, MOVIES_SITEMAP_1)
            if "movies/sitemap/2.xml" in url:
                return (200, MOVIES_SITEMAP_2)
            if "movies/sitemap/3.xml" in url:
                return (404, "")
            if "/movie/" in url:
                if "scene" in url:
                    return (200, MOVIE_HTML_NO_STREAM)
                return (200, MOVIE_HTML.replace(
                    "all-pass/10285268178004214",
                    url.split("/movie/")[1].split("/")[0] + "/" +
                    url.rstrip("/").split("/")[-1]).replace(
                    '"name":"All Pass"',
                    '"name":"%s"' % url.split("/movie/")[1].split("/")[0]))
            return (404, "")

        totals = ct.sync(db_path=db, limit=4, fetcher=fake_fetch,
                         prober=probe_ok, delay=0)
        # 3 movies from sitemap 1 + scene (no stream, skipped) from
        # sitemap 2; the /series/ loc in sitemap 2 is never fetched.
        self.assertEqual(totals["posts_written"], 3)
        self.assertEqual(totals["skipped"], 1)
        ok, result = ct.verify_db(db)
        self.assertTrue(ok)
        self.assertEqual(result["posts"], 3)

    def test_sync_with_no_movie_urls_writes_nothing(self):
        db = self._tmp_db()
        totals = ct.sync(db_path=db, limit=5,
                         fetcher=lambda url: (404, ""), prober=probe_ok,
                         delay=0)
        self.assertEqual(totals["posts_written"], 0)


if __name__ == "__main__":
    unittest.main()
