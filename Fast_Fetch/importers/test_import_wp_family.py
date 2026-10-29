#!/usr/bin/env python3
"""
test_import_wp_family.py — offline unit tests for the WordPress-family importer.

No network: every case feeds a captured page shape into parse_page and writes
into a temp staging file.
"""

from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import import_wp_family as wp  # noqa: E402

MOVIE_PAGE = """<!DOCTYPE html><html><head>
<title>Jawan (2023) Full Movie Download MoviesMela</title>
<meta property="og:title" content="Jawan (2023) Full Movie Download">
<meta property="og:description" content="A soldier takes on corruption.">
<meta property="og:image" content="https://cdn.moviesmela.com/jawan.jpg">
<meta name="keywords" content="Jawan, Hindi">
</head><body>
<h1>Jawan (2023)</h1>
<iframe src="https://pkembed.site/e/abc123"></iframe>
<iframe src="https://doubleclick.net/pixel"></iframe>
<div class="dl">
 <a href="https://cdn.moviesmela.com/jawan-720p.mkv">Jawan 2023 720p WEB-DL 1.2GB</a>
 <a href="https://cdn.moviesmela.com/jawan-1080p.mkv">Jawan 2023 1080p WEB-DL 3.5 GB</a>
</div>
<a rel="tag" href="/tag/action">Action</a>
<a rel="tag" href="/tag/thriller">Thriller</a>
</body></html>"""

SERIES_PAGE = """<html><head>
<meta property="og:title" content="Mirzapur Season 2 Episode 3 Hindi Complete Series">
<meta property="og:description" content="Mafia saga.">
</head><body>
<h1>Mirzapur S02E03</h1>
<iframe src="//player.example.com/e/mp-203"></iframe>
<a href="https://cdn.example.com/mirzapur-s02e03-720p.mkv">Mirzapur S02E03 720p 500MB</a>
</body></html>"""

ADULT_PAGE = """<html><head>
<meta property="og:title" content="Palang Tod Season 1 (2024) Ullu Web Series">
</head><body>
<iframe src="https://player.example.com/e/adult1"></iframe>
</body></html>"""

PAGE_NO_PLAYER = """<html><head>
<meta property="og:title" content="About Us">
</head><body><h1>About</h1><p>Contact us.</p></body></html>"""


class ParsePageTests(unittest.TestCase):
    def test_movie_page_splits_iframe_and_quality_anchors(self):
        post = wp.parse_page(MOVIE_PAGE, "https://www.moviesmela.com/jawan-2023/", "moviesmela")
        self.assertIsNotNone(post)
        self.assertEqual(post["clean_title"], "Jawan")
        self.assertEqual(post["year"], 2023)
        self.assertEqual(post["content_type"], "movie")
        self.assertEqual(post["is_18_plus"], 0)
        self.assertEqual(post["poster_url"], "https://cdn.moviesmela.com/jawan.jpg")
        self.assertIn("Action", post["genres"])
        kinds = [rel["sources"][0]["playback_type"] for rel in post["releases"]]
        self.assertIn("iframe", kinds)
        self.assertEqual(kinds.count("download"), 2, "each quality is its own release")

    def test_ad_network_iframe_is_dropped(self):
        post = wp.parse_page(MOVIE_PAGE, "https://www.moviesmela.com/jawan-2023/", "moviesmela")
        urls = [s["source_url"] for rel in post["releases"] for s in rel["sources"]]
        self.assertFalse(any("doubleclick" in u for u in urls))

    def test_protocol_relative_iframe_gets_https(self):
        post = wp.parse_page(SERIES_PAGE, "https://thebollyflix.gen.in/mirzapur-s02e03/", "bollyflix")
        iframes = [s["source_url"] for rel in post["releases"]
                   for s in rel["sources"] if s["playback_type"] == "iframe"]
        self.assertEqual(iframes, ["https://player.example.com/e/mp-203"])

    def test_series_page_carries_season_and_episode(self):
        post = wp.parse_page(SERIES_PAGE, "https://thebollyflix.gen.in/mirzapur-s02e03/", "bollyflix")
        self.assertEqual(post["content_type"], "series")
        self.assertEqual(post["season_number"], 2)
        rel = post["releases"][0]
        self.assertEqual(rel["season"], 2)
        self.assertEqual(rel["episode"], 3)

    def test_adult_title_is_flagged_at_parse_time(self):
        post = wp.parse_page(ADULT_PAGE, "https://moviehax.run/palang-tod-season-1/", "moviehax")
        self.assertEqual(post["is_18_plus"], 1)

    def test_page_without_playable_object_returns_none(self):
        self.assertIsNone(wp.parse_page(PAGE_NO_PLAYER, "https://animeworld.live/about/", "animeworld"))

    def test_size_is_parsed_to_bytes(self):
        self.assertEqual(wp._size_bytes("1.2GB"), int(1.2 * 1024 ** 3))
        self.assertEqual(wp._size_bytes("500 mb"), 500 * 1024 ** 2)
        self.assertIsNone(wp._size_bytes("no size"))

    def test_lazyloaded_iframe_is_read_and_about_blank_skipped(self):
        html = ('<iframe data-lazyloaded="1" src="about:blank" '
                'data-litespeed-src="https://hindidubbedmovies.pk/?trembed=0&#038;trid=8&trtype=1">'
                '</iframe>')
        got = wp._sources_from_html(html, "https://hindidubbedmovies.pk/movies/maidaan-m/")
        self.assertEqual([s["source_url"] for s in got],
                         ["https://hindidubbedmovies.pk/?trembed=0&trid=8&trtype=1"])

    def test_player_host_config_catches_a_url_printed_outside_an_iframe(self):
        html = '<p>Server: https://abscloud.org/1/edd6c03c3f514d31556b9044017614be</p>'
        cfg = {"base": "https://hindianimeszone.com", "player_hosts": ["abscloud.org"]}
        got = wp._sources_from_html(html, "https://hindianimeszone.com/x/", cfg)
        self.assertEqual([s["source_url"] for s in got],
                         ["https://abscloud.org/1/edd6c03c3f514d31556b9044017614be"])

    def test_category_shelf_links_are_not_download_sources(self):
        html = ('<a href="https://thebollyflix.gen.in/movies-by-quality/720p-movies/">'
                '720p MOVIES</a>'
                '<a class="hsl" href="https://mobilejsr.com/view/088MKgTAey">720p [318MB]</a>')
        cfg = {"base": "https://thebollyflix.gen.in", "internal_hosts": ["bollyflix.co.za"]}
        got = wp._sources_from_html(html, "https://thebollyflix.gen.in/x/", cfg)
        self.assertEqual([s["source_url"] for s in got],
                         ["https://mobilejsr.com/view/088MKgTAey"])

    def test_first_party_download_button_is_kept(self):
        html = ('<a rel="nofollow" href="https://hindidubbedmovies.pk/?trdownload=1&#038;trid=8"'
                ' class="Button">Download</a>')
        cfg = {"base": "https://hindidubbedmovies.pk"}
        got = wp._sources_from_html(html, "https://hindidubbedmovies.pk/movies/x/", cfg)
        self.assertEqual([s["source_url"] for s in got],
                         ["https://hindidubbedmovies.pk/?trdownload=1&trid=8"])

    def test_generic_og_title_falls_back_to_description_head(self):
        page = ('<html><head><meta property="og:title" content="Bollyflix">'
                '<meta property="og:description" content="Girth Meets Lily (2026) Brazzers '
                'Originals English Adult Video 720p HDRip Title: Girth Meets Lily '
                '(2026) Genres: Erotic">'
                '<title>Bollyflix</title></head><body>'
                '<iframe src="https://mobilejsr.com/view/abc"></iframe></body></html>')
        post = wp.parse_page(page, "https://thebollyflix.gen.in/girth-meets-lily-2026/",
                             "bollyflix")
        self.assertIsNotNone(post)
        self.assertEqual(post["title"], "Girth Meets Lily (2026) Brazzers Originals English Adult Video")
        self.assertEqual(post["is_18_plus"], 1)


class ExportStagingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "wp.db"

    def tearDown(self):
        self.tmp.cleanup()

    def test_export_writes_post_release_source_and_sitemap_row(self):
        post = wp.parse_page(MOVIE_PAGE, "https://www.moviesmela.com/jawan-2023/", "moviesmela")
        out = wp.export_staging(self.db, "moviesmela", [post])
        self.assertEqual(out["posts_written"], 1)
        self.assertGreaterEqual(out["releases_written"], 2)
        self.assertGreaterEqual(out["sources_written"], 3)
        conn = sqlite3.connect(self.db)
        try:
            row = conn.execute("SELECT title, media_type, is_18_plus, source_site"
                               " FROM posts").fetchone()
            self.assertEqual(row[1], "movie")
            self.assertEqual(row[2], 0)
            self.assertEqual(row[3], "moviesmela")
            src = conn.execute("SELECT status, is_temporary FROM sources").fetchone()
            self.assertEqual(src, ("unverified", 0))
            sm = conn.execute("SELECT scraped FROM sitemap_cache").fetchone()
            self.assertEqual(sm[0], 1)
        finally:
            conn.close()

    def test_reexport_replaces_this_pages_releases_not_the_posts(self):
        post = wp.parse_page(MOVIE_PAGE, "https://www.moviesmela.com/jawan-2023/", "moviesmela")
        wp.export_staging(self.db, "moviesmela", [post])
        conn = sqlite3.connect(self.db)
        first = conn.execute("SELECT COUNT(*) FROM releases").fetchone()[0]
        conn.close()
        wp.export_staging(self.db, "moviesmela", [post])
        conn = sqlite3.connect(self.db)
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM releases").fetchone()[0], first)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0], 1)
        finally:
            conn.close()

    def test_adult_flag_survives_upsert(self):
        adult = wp.parse_page(ADULT_PAGE, "https://moviehax.run/palang-tod-season-1/", "moviehax")
        wp.export_staging(self.db, "moviehax", [adult])
        moviehax_clean = dict(adult, is_18_plus=0)
        wp.export_staging(self.db, "moviehax", [moviehax_clean])
        conn = sqlite3.connect(self.db)
        try:
            self.assertEqual(
                conn.execute("SELECT is_18_plus FROM posts").fetchone()[0], 1)
        finally:
            conn.close()


class SyncAndCrawlTests(unittest.TestCase):
    def test_sitemap_parser_reads_loc_and_lastmod(self):
        text = ("<urlset><url><loc>https://x.site/a-2023/</loc>"
                "<lastmod>2024-01-01</lastmod></url>"
                "<url><loc>https://x.site/b/</loc></url></urlset>")
        self.assertEqual(wp.parse_sitemap(text),
                         [("https://x.site/a-2023/", "2024-01-01"),
                          ("https://x.site/b/", None)])

    def test_cdata_wrapped_locs_are_unwrapped(self):
        text = ("<sitemapindex><sitemap><loc><![CDATA[https://x.site/addl-sitemap.xml]]></loc>"
                "<lastmod><![CDATA[2026-10-28T16:04:02+00:00]]></lastmod></sitemap>"
                "</sitemapindex>")
        self.assertEqual(wp.parse_sitemap(text),
                         [("https://x.site/addl-sitemap.xml", "2026-10-28T16:04:02+00:00")])

    def test_rest_seed_pages_until_x_wp_totalpages(self):
        payloads = {
            1: ('[{"link":"https://x.site/one-2024/"},{"link":"https://x.site/category/a/"}]',
                {"x-wp-totalpages": "2"}),
            2: ('[{"link":"https://x.site/two-2024/"}]', {}),
        }

        def fake_full(url, **_kw):
            page = 2 if "page=2" in url else 1
            text, headers = payloads[page]
            return 200, url, text, headers

        cfg = {"base": "https://x.site", "sitemaps": [],
               "rest": "https://x.site/wp-json/wp/v2/posts",
               "exclude": r"/category/"}
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(wp, "_http_get_full", side_effect=fake_full):
            db = Path(tmp) / "x.db"
            fresh = wp.sync_catalog("bollyflix", db, config=cfg, verbose=False)
            self.assertEqual(fresh, 2)
            conn = sqlite3.connect(db)
            try:
                self.assertEqual(
                    conn.execute("SELECT loc FROM sitemap_cache ORDER BY loc").fetchall(),
                    [("https://x.site/one-2024/",), ("https://x.site/two-2024/",)])
            finally:
                conn.close()

    def test_sync_follows_index_and_filters_excluded_paths(self):
        index = "<sitemapindex><sitemap><loc>https://x.site/post-sitemap.xml</loc></sitemap></sitemapindex>"
        child = ("<urlset><url><loc>https://x.site/good-film-2023/</loc></url>"
                 "<url><loc>https://x.site/category/action/</loc></url></urlset>")
        cfg = {"base": "https://x.site", "sitemaps": ["https://x.site/sitemap_index.xml"],
               "exclude": r"/(?:category|tag)/"}

        def fake_get(url, **_kw):
            return (200, url, index) if url.endswith("index.xml") else (200, url, child)

        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(wp, "http_get", side_effect=fake_get):
            db = Path(tmp) / "x.db"
            fresh = wp.sync_catalog("moviesmela", db, config=cfg, verbose=False)
            self.assertEqual(fresh, 1)
            conn = sqlite3.connect(db)
            try:
                self.assertEqual(
                    conn.execute("SELECT loc FROM sitemap_cache").fetchall(),
                    [("https://x.site/good-film-2023/",)])
            finally:
                conn.close()

    def test_a_429_pauses_the_run_without_spending_attempts(self):
        def fake_get(url, **_kw):
            return 429, url, ""

        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "x.db"
            conn = sqlite3.connect(db)
            try:
                wp.ensure_schema(conn)
                conn.executemany(
                    "INSERT INTO sitemap_cache (loc, scraped) VALUES (?, 0)",
                    [("https://x.site/a/",), ("https://x.site/b/",), ("https://x.site/c/",)])
                conn.commit()
            finally:
                conn.close()
            with mock.patch.object(wp, "http_get", side_effect=fake_get):
                totals = wp.crawl("moviesmela", db, delay=0, verbose=False)
            self.assertEqual(totals["pages"], 1, "later rows are skipped, not fetched")
            self.assertEqual(totals["paused_rate_limit"], 2)
            self.assertTrue(wp._RATE_LIMITED.is_set())
            conn = sqlite3.connect(db)
            try:
                self.assertEqual(conn.execute(
                    "SELECT COUNT(*) FROM sitemap_cache WHERE error_count = 1").fetchone()[0], 1)
                self.assertEqual(conn.execute(
                    "SELECT COUNT(*) FROM sitemap_cache WHERE error_count = 0").fetchone()[0], 2)
            finally:
                conn.close()

    def test_a_404_is_parked_with_a_reason(self):
        def fake_get(url, **_kw):
            return 404, url, ""

        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "x.db"
            conn = sqlite3.connect(db)
            try:
                wp.ensure_schema(conn)
                conn.execute("INSERT INTO sitemap_cache (loc, scraped) VALUES ('https://x.site/a/', 0)")
                conn.commit()
            finally:
                conn.close()
            with mock.patch.object(wp, "http_get", side_effect=fake_get):
                totals = wp.crawl("moviesmela", db, delay=0, verbose=False)
            self.assertEqual(totals["declined_by_reason"], {"http-404": 1})
            conn = sqlite3.connect(db)
            try:
                self.assertEqual(conn.execute(
                    "SELECT scraped FROM sitemap_cache").fetchone()[0], -1)
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
