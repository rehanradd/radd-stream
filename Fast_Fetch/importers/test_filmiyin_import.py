#!/usr/bin/env python3
"""
test_filmiyin_import.py — Offline unit tests for the filmiy.in staging importer.

No network: every HTTP call is patched. Run from Fast_Fetch/importers/:
    python3 -S test_filmiyin_import.py
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import import_filmiyin as fi

PAGE_URL = "https://filmiy.in/ohm-shanthi-oshaana-2014-hindi-malayalam-dual-audio-uncut-south-movie-hd-esub.html"
BRIDGE_1 = "https://new1.filesdl.co/cloud/eyJpdiI6IldWQjA2d1RxSzlWVlkwNyIsInRhZyI6IngifQ"
BRIDGE_2 = "https://new1.filesdl.co/cloud/eyJpdiI6Ik5TUFVKS25YM3dQQ2I1OCIsInRhZyI6InkifQ"

FIXTURE = f"""
<html><head>
<title>Ohm Shanthi Oshaana (2014) (Hindi + Malayalam) Dual Audio UnCut South Movie HD ESub &raquo; FilmyFly 2026 &ndash; Bollywood, South Hindi Dubbed, Hollywood Movies &amp; Web Series</title>
<meta property="og:image" content="https://filmiy.in/uploads/posts/covers/photo_ohm-shanthi-oshaana-2014-hindi-malayalam-dual-audio-uncut-south-movie-hd-esub.png">
<meta property="og:description" content="Pooja Mathew wants a love marriage.">
<meta name="keywords" content="FilmyFly 2026, Filmy4Wap, Ohm Shanthi Oshaana">
</head><body>
<h2>Ohm Shanthi Oshaana (2014) (Hindi + Malayalam) Dual Audio UnCut South Movie HD ESub</h2>
<img class="movie-cover" src="/uploads/posts/covers/photo_ohm-shanthi-oshaana-2014-hindi-malayalam-dual-audio-uncut-south-movie-hd-esub.png">
<img src="/uploads/posts/screenshot/screenshot_ohm-shanthi-oshaana-2014-hindi-malayalam-dual-audio-uncut-south-movie-hd-esub.png">
<img class="row-thumb" src="/uploads/posts/imagecloud/imagecloud_legend-2014-hindi-telugu-dual-audio-uncut-movie-hd-esub.png">
<div class="movie-info">
  <div class="fname"><strong>Name:</strong> <span>Ohm Shanthi Oshaana (2014)</span></div>
  <div class="fname"><strong>Genre:</strong> <span>Comedy, Romance</span></div>
  <div class="fname"><strong>Duration:</strong> <span>2h 4min</span></div>
  <div class="fname"><strong>Release Date:</strong> <span>2014</span></div>
  <div class="fname"><strong>Language:</strong> <span>Hindi + Malayalam</span></div>
  <div class="fname"><strong>Starcast:</strong> <span>Nazriya Nazim, Nivin Pauly</span></div>
  <div class="fname"><strong>Size:</strong> <span>440Mb 2.5Gb HD</span></div>
  <div class="fname"><strong>Description:</strong> <span>Pooja Mathew wants a love marriage.</span></div>
</div>
<h3>Download This Movie</h3>
<div class="dlink dl"><a href="{BRIDGE_1}" target="_blank" rel="noopener noreferrer" title="mirror"><div class="dll"> Download 440Mb {{480p-HEVC}}</div></a></div>
<div class="dlink dl"><a href="{BRIDGE_2}" target="_blank" rel="noopener noreferrer" title="mirror"><div class="dll"> Download 2.5Gb {{1080p-WEB-DL}}</div></a></div>
<h3>Related Movies</h3>
<a href="https://filmiy.in/legend-2014-hindi-telugu-dual-audio-uncut-movie-hd-esub.html">Legend (2014) {{Hindi + Telugu}} Dual Audio UnCut Movie HD ESub HEVC</a>
<a href="/page-how-to-download-movie.html">How To Download Movies Filmy4wap</a>
<a href="https://filmyspark.com/">Filmyfly.Fo</a>
<a href="https://t.me/+r9lsBkGjARwyZTM8">Join Our Telegram</a>
<img src="//sstatic1.histats.com/0.gif?5035919&amp;101" alt="site stats">
</body></html>
"""

JS_GATE = "<html><title>Just a moment</title><body>Enable JavaScript and cookies to continue</body></html>"


def parse_fixture(url: str = PAGE_URL) -> dict:
    return fi.parse_page(FIXTURE, url=url)


class TestTitleCleaning(unittest.TestCase):
    def test_strips_packaging_descriptors(self):
        d = fi.parse_title(
            "Tu Hai Meri Kiran (2026) Bollywood Hindi Movie HQCam",
            "tu-hai-meri-kiran-2026-bollywood-hindi-movie-hqcam")
        self.assertEqual(d["clean_title"], "Tu Hai Meri Kiran")
        self.assertEqual(d["year"], 2026)
        self.assertEqual(d["media_type"], "movie")

    def test_keeps_alternate_title_parenthetical(self):
        d = fi.parse_title(
            "Pyaar Reloaded (Naan Sigappu Manithan) (2014) (Hindi + Tamil) Dual Audio UnCut South Movie HD ESub",
            "")
        self.assertEqual(d["clean_title"], "Pyaar Reloaded (Naan Sigappu Manithan)")

    def test_does_not_retitle_a_movie_called_hindi_medium(self):
        d = fi.parse_title("Hindi Medium (2017) (Hindi) Full Movie HD ESub", "")
        self.assertEqual(d["clean_title"], "Hindi Medium")

    def test_series_season_and_completeness(self):
        d = fi.parse_title("Matargashti S01 (2026) Hindi Completed Web Series HEVC ESub",
                           "matargashti-s01-2026-hindi-completed-web-series-hevc-esub")
        self.assertEqual(d["clean_title"], "Matargashti")
        self.assertEqual(d["season_number"], 1)
        self.assertEqual(d["media_type"], "complete_season")

    def test_age_certificate_is_not_part_of_the_title(self):
        d = fi.parse_title("Eyes (18+) (2026) Hindi Movie HD ESub", "")
        self.assertNotIn("18+", d["clean_title"])

    def test_canonical_key_is_slug_stable(self):
        """The key must survive a parser change, or re-scrapes strand old rows."""
        slug = "ohm-shanthi-oshaana-2014-hindi-malayalam-dual-audio-uncut-south-movie-hd-esub"
        self.assertEqual(fi.build_canonical_key("Whatever The Cleaner Says", 2014, None, None, slug),
                         "ohm-shanthi-oshaana_2014")
        self.assertEqual(fi.build_canonical_key("x", 2026, 5, None,
                         "the-great-indian-kapil-show-s05-2026-hindi-completed-web-series-hevc-esub-episode-04-add"),
                         "the-great-indian-kapil-show_2026_s05")

    def test_numeric_titles_keep_their_number(self):
        self.assertEqual(fi._slug_title_base("3-idiots-2009-hindi-bluray-1080p-esub"), "3-idiots")


class TestSizeParsing(unittest.TestCase):
    def test_sizes(self):
        self.assertEqual(fi.parse_size_to_bytes("Download 440Mb {480p-HEVC}"), 440 * 1024 ** 2)
        self.assertEqual(fi.parse_size_to_bytes("Download 1.1Gb {720p-HD}"), int(1.1 * 1024 ** 3))
        self.assertIsNone(fi.parse_size_to_bytes("Download HD"))


class TestAdultFlagging(unittest.TestCase):
    def test_flags_only_explicit_signals(self):
        self.assertEqual(fi.is_adult_content("Eyes (18+) Hindi"), True)
        self.assertEqual(fi.is_adult_content("Blue Film 2024"), True)
        self.assertEqual(fi.is_adult_content("Ohm Shanthi Oshaana Dual Audio UnCut"), False)

    def test_uncut_is_not_adult_on_this_site(self):
        """Every title here says UnCut; treating it as 18+ would hide the catalog."""
        self.assertEqual(fi.is_adult_content("UnCut South Movie HD ESub"), False)

    def test_ambiguous_words_in_prose_do_not_flag(self):
        """Hiding a mainstream series costs more than one missed flag."""
        blurb = ("a bold, glamorous couple; a story of lust and sensual "
                 "temptation")
        self.assertEqual(fi.is_adult_content("Dil Padosi S01", prose=(blurb,)), False)

    def test_ambiguous_words_as_shelf_labels_do_flag(self):
        self.assertEqual(fi.is_adult_content("Dil Padosi S01", "Bold, Romance"), True)
        self.assertEqual(fi.is_adult_content("Mocktail S01", prose=("18+",)), True)


class TestBrandScrubbing(unittest.TestCase):
    def test_scrubs_site_names_from_display_strings(self):
        self.assertNotIn("FilmyFly", fi.scrub_brand("FilmyFly 2026, Filmy4Web Movies Download"))
        self.assertEqual(fi.scrub_brand("FilmyFly"), "")

    def test_synopsis_and_keywords_are_clean(self):
        post = parse_fixture()
        self.assertNotIn("filmy", post["synopsis"].lower())
        self.assertNotIn("filmy", post["clean_title"].lower())


class TestLinkHarvesting(unittest.TestCase):
    def test_only_foreign_media_links_become_sources(self):
        """Same-host cards look like downloads ('... HEVC') but are navigation."""
        post = parse_fixture()
        urls = [s["source_url"] for r in post["releases"] for s in r["sources"]]
        self.assertEqual(len(urls), 2)
        for url in urls:
            self.assertIn("filesdl.co", url)
            self.assertNotIn("filmiy.in", url)

    def test_quality_codec_and_size_per_print(self):
        post = parse_fixture()
        first = post["releases"][0]
        self.assertEqual(first["quality"], "480p")
        self.assertEqual(first["codec"], "HEVC")
        self.assertEqual(first["size_bytes"], 440 * 1024 ** 2)
        second = post["releases"][1]
        self.assertEqual(second["quality"], "1080p")
        self.assertEqual(second["codec"], "WEBDL")

    def test_tracker_pixel_is_never_a_source(self):
        post = parse_fixture()
        blob = json.dumps([s for r in post["releases"] for s in r["sources"]])
        self.assertNotIn("histats", blob)

    def test_embed_iframes_become_watch_sources(self):
        html = FIXTURE.replace("<h3>Download This Movie</h3>",
                               '<iframe src="https://embed.example.net/player/abc123"></iframe>'
                               '<h3>Download This Movie</h3>')
        post = fi.parse_page(html, url=PAGE_URL)
        embeds = [s for r in post["releases"] for s in r["sources"]
                  if s["playback_type"] == "embed"]
        self.assertEqual(len(embeds), 1)
        self.assertEqual(embeds[0]["status"], "active")

    def test_watch_only_page_keeps_a_release(self):
        html = ('<h2>Dune Part Two (2024) HD ESub</h2>'
                '<iframe src="https://embed.example.net/player/zz"></iframe>')
        post = fi.parse_page(html, url="https://filmiy.in/dune-part-two-2024-hd-esub.html")
        self.assertEqual(len(post["releases"]), 1)
        self.assertEqual(post["releases"][0]["label"], "Watch")


class TestParsePage(unittest.TestCase):
    def test_metadata_shape(self):
        post = parse_fixture()
        self.assertEqual(post["clean_title"], "Ohm Shanthi Oshaana")
        self.assertEqual(post["year"], 2014)
        self.assertEqual(post["source_site"], "filmiyin")
        self.assertEqual(post["canonical_key"], "ohm-shanthi-oshaana_2014")
        self.assertEqual(post["genres"], "Comedy, Romance")
        self.assertEqual(post["duration"], "2h 4min")
        self.assertEqual(post["cast_names"], "Nazriya Nazim, Nivin Pauly")
        self.assertEqual(sorted(post["languages"].split(", ")), ["Hindi", "Malayalam"])
        self.assertEqual(post["is_18_plus"], 0)

    def test_artwork_is_scoped_to_this_title(self):
        post = parse_fixture()
        self.assertTrue(post["poster_url"].endswith(
            "photo_ohm-shanthi-oshaana-2014-hindi-malayalam-dual-audio-uncut-south-movie-hd-esub.png"))
        # imagecloud_* belongs to a related card, never to this page.
        self.assertFalse(any("imagecloud" in b for b in post["backdrop_urls"]))
        self.assertEqual(len(post["backdrop_urls"]), 1)

    def test_industry_classification(self):
        self.assertEqual(fi.classify(parse_fixture()), {"industry": "Mollywood", "country": "India"})

    def test_non_catalog_pages_return_none(self):
        self.assertIsNone(fi.parse_page(FIXTURE, url="https://filmiy.in/south-hindi-dubbed-movie/"))
        self.assertIsNone(fi.parse_page(FIXTURE, url="https://filmiy.in/page-how-to-download-movie.html"))

    def test_accepts_a_bare_url(self):
        with patch.object(fi, "http_get", return_value=(200, PAGE_URL, FIXTURE)):
            post = fi.parse_page(PAGE_URL)
        self.assertEqual(post["canonical_key"], "ohm-shanthi-oshaana_2014")

    def test_unreachable_page_returns_none(self):
        with patch.object(fi, "http_get", return_value=(503, PAGE_URL, "")):
            self.assertIsNone(fi.parse_page(PAGE_URL))


class TestResolveLinks(unittest.TestCase):
    def test_js_challenge_keeps_the_bridge_and_marks_it(self):
        post = parse_fixture()
        with patch.object(fi, "http_get", return_value=(403, fi.BASE_URL, JS_GATE)):
            fi.resolve_links(post)
        for rel in post["releases"]:
            src = rel["sources"][0]
            self.assertEqual(src["status"], "js_required")
            self.assertEqual(src["final_url"], src["source_url"])
            self.assertEqual(src["is_temporary"], 0)

    def test_dead_link_is_recorded_not_dropped(self):
        post = parse_fixture()
        with patch.object(fi, "http_get", return_value=(404, fi.BASE_URL, "Not found")):
            fi.resolve_links(post)
        statuses = {r["sources"][0]["status"] for r in post["releases"]}
        self.assertEqual(statuses, {"dead"})
        self.assertEqual(len(post["releases"]), 2)

    def test_direct_cdn_redirect_is_active(self):
        cdn = "https://video-downloads.googleusercontent.com/abc"
        post = parse_fixture()
        with patch.object(fi, "http_get", return_value=(200, cdn, "")):
            fi.resolve_links(post)
        for rel in post["releases"]:
            self.assertEqual(rel["sources"][0]["status"], "active")
            self.assertEqual(rel["sources"][0]["final_url"], cdn)

    def test_network_error_does_not_lose_the_link(self):
        post = parse_fixture()
        with patch.object(fi, "http_get", return_value=(0, "", "[network error] timed out")):
            fi.resolve_links(post)
        self.assertEqual({r["sources"][0]["status"] for r in post["releases"]}, {"error"})


class TestStagingDatabase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "filmiyin.db"

    def tearDown(self):
        self.tmp.cleanup()

    def test_export_creates_isolated_staging_schema(self):
        fi.export_staging(self.db, [parse_fixture()])
        conn = sqlite3.connect(self.db)
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue({"sitemap_cache", "posts", "releases", "sources"} <= tables)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0], 2)
        conn.close()

    def test_reexport_is_idempotent(self):
        post = parse_fixture()
        first = fi.export_staging(self.db, [post])
        second = fi.export_staging(self.db, [post])
        conn = sqlite3.connect(self.db)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0], 1)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM releases").fetchone()[0], 2)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0], 2)
        conn.close()
        self.assertEqual(first["releases_written"], second["releases_written"])

    def test_source_site_is_stamped_on_every_row(self):
        fi.export_staging(self.db, [parse_fixture()])
        conn = sqlite3.connect(self.db)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT source_site, url, raw_meta FROM posts").fetchone()
        self.assertEqual(row["source_site"], "filmiyin")
        self.assertEqual(json.loads(row["raw_meta"])["bridge_count"], 2)
        conn.close()

    def test_empty_and_headless_posts_are_skipped(self):
        stats = fi.export_staging(self.db, [{"clean_title": "X", "canonical_key": "x", "releases": []},
                                            None])
        self.assertEqual(stats["posts_written"], 0)
        self.assertEqual(stats["skipped"], 2)

    def test_two_pages_of_one_title_keep_their_own_prints(self):
        """Replacing per site/per key was the documented data-loss bug; it must be per page."""
        a = parse_fixture()
        b = parse_fixture()
        b["url"] = "https://filmiy.in/ohm-shanthi-oshaana-2014-episode-pack-reupload.html"
        b["slug"] = "ohm-shanthi-oshaana-2014-episode-pack-reupload"
        b["canonical_key"] = a["canonical_key"]  # the site re-uploaded the same title
        b["releases"] = [dict(a["releases"][0], label="Download 880Mb {480p-HEVC}")]
        fi.export_staging(self.db, [a, b])
        conn = sqlite3.connect(self.db)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM releases").fetchone()[0], 3)
        # Re-scraping page A must not touch page B's print.
        fi.export_staging(self.db, [a])
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM releases").fetchone()[0], 3)
        conn.close()

    def test_sync_catalog_queues_only_post_pages(self):
        xml = ('<urlset><url><loc>https://filmiy.in/south-hindi-dubbed-movie/</loc></url>'
               f'<url><loc>{PAGE_URL}</loc></url>'
               '<url><loc>https://filmiy.in/page-how-to-download-movie.html</loc></url></urlset>')
        with patch.object(fi, "http_get", return_value=(200, fi.SITEMAP_URL, xml)):
            added = fi.sync_catalog(db_path=self.db, verbose=False)
        conn = sqlite3.connect(self.db)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM sitemap_cache").fetchone()[0], added)
        self.assertEqual(added, 1)
        conn.close()

    def test_crawl_marks_pages_indexed(self):
        xml = f'<urlset><url><loc>{PAGE_URL}</loc></url></urlset>'
        with patch.object(fi, "http_get", return_value=(200, fi.SITEMAP_URL, xml)):
            fi.sync_catalog(db_path=self.db, verbose=False)
        responses = {"calls": 0}

        def fake(url, timeout=30, retries=3):
            if url.endswith(".html") and "filesdl" not in url:
                return 200, url, FIXTURE
            responses["calls"] += 1
            return 403, url, JS_GATE

        with patch.object(fi, "http_get", side_effect=fake):
            totals = fi.crawl_pending(db_path=self.db, workers=1, delay=0, verbose=False)
        self.assertEqual(totals["posts"], 1)
        self.assertEqual(totals["releases"], 2)
        conn = sqlite3.connect(self.db)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM sitemap_cache WHERE scraped=1").fetchone()[0], 1)
        conn.close()


class TestMergeCatalogsContract(unittest.TestCase):
    def setUp(self):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "filmiyin.db"

    def tearDown(self):
        self.tmp.cleanup()

    def test_staging_rows_map_onto_the_unified_shape(self):
        try:
            import merge_catalogs as mc
        except Exception:
            self.skipTest("merge_catalogs not importable in this environment")
        fi.export_staging(self.db, [parse_fixture()])
        conn = sqlite3.connect(self.db)
        conn.row_factory = sqlite3.Row
        post = conn.execute("SELECT * FROM posts").fetchone()
        mapped = mc._collect_staging_post(conn, post, "filmiyin")
        self.assertEqual(mapped["source_site"], "filmiyin")
        self.assertEqual(mapped["content_type"], "movie")
        self.assertEqual(len(mapped["releases"]), 2)
        self.assertEqual(mapped["releases"][0]["quality"], "480p")
        # An un-probed mirror is stored honestly, never silently as active.
        self.assertEqual(mapped["releases"][0]["sources"][0]["status"], "unknown")
        conn.close()

    def test_probed_status_survives_the_round_trip(self):
        try:
            import merge_catalogs as mc
        except Exception:
            self.skipTest("merge_catalogs not importable in this environment")
        post = parse_fixture()
        with patch.object(fi, "http_get", return_value=(403, fi.BASE_URL, JS_GATE)):
            fi.resolve_links(post)
        fi.export_staging(self.db, [post])
        conn = sqlite3.connect(self.db)
        conn.row_factory = sqlite3.Row
        mapped = mc._collect_staging_post(conn, conn.execute("SELECT * FROM posts").fetchone(), "filmiyin")
        self.assertEqual(mapped["releases"][0]["sources"][0]["status"], "js_required")
        self.assertEqual(mapped["releases"][0]["sources"][0]["final_url"],
                         mapped["releases"][0]["sources"][0]["source_url"])
        conn.close()


if __name__ == "__main__":
    unittest.main()
