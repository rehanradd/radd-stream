#!/usr/bin/env python3
"""
test_missav_import.py — offline unit tests for the MissAV importer.

No test touches the network: every fetch is a fake and every fixture is shaped
from pages measured live on 2026-11-11 (the sitemap index + items_1 probe).
The rules this suite keeps, and the measured fact each one exists because of:

* missav.ws HTML is Cloudflare-walled (403 "Just a moment...") from every
  fetch path tried (urllib, curl, browser tool), on .ws, .live and .com alike.
  The XML sitemap is NOT walled: /sitemap.xml is a 559-entry index and each
  sitemap_items_N.xml holds up to ~13,000 video URLs. So enumeration is
  sitemap-only; a video page fetch is best-effort enrichment, never required.
* A <url> block carries no title/poster metadata — only <loc> plus xhtml
  alternates. The English page (/dmNN/en/<code>) is the canonical video URL
  and the JAV code is the last path segment. The code IS the title until a
  page fetch upgrades it (OpenGraph og:title / og:image / og:video:*).
* The m3u8 lives in obfuscated pipe-delimited JS on the video page. It is NOT
  extracted here (Phase C crack task); the importer stores the video page as
  the bridge source (playback_type "url", status "unverified" — never claimed
  playable).
* EVERY row is is_18_plus = 1, by site authority (ADULT_SOURCE_SITES) and by
  the importer's own assert — even for a code/title with no adult token.
  The merge preserves it (save_scraped_data ORs the incoming flag; the upsert
  takes MAX). The server hides flagged rows from every public surface
  (redact.adult_clause in the posts query; the App never receives is_18_plus).
"""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fast_fetch  # noqa: E402
import import_missav as mv  # noqa: E402

SAMPLE_INDEX_XML = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <sitemap><loc>https://missav.ws/sitemap_pages.xml</loc></sitemap>
    <sitemap><loc>https://missav.ws/sitemap_items_1.xml</loc></sitemap>
    <sitemap><loc>https://missav.ws/sitemap_items_2.xml</loc></sitemap>
    <sitemap><loc>https://missav.ws/sitemap_actresses_1.xml</loc></sitemap>
</sitemapindex>"""

# Shaped from the real sitemap_items_1.xml (2026-11-11): one <url> per video,
# default <loc> plus the hreflang="en" alternate that carries the code.
SAMPLE_ITEMS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:xhtml="http://www.w3.org/1999/xhtml">
    <url>
    <loc>https://missav.ws/dm32/qmill-001</loc>
    <xhtml:link rel="alternate" hreflang="zh" href="https://missav.ws/dm32/qmill-001" />
    <xhtml:link rel="alternate" hreflang="en" href="https://missav.ws/dm32/en/qmill-001" />
    <xhtml:link rel="alternate" hreflang="ja" href="https://missav.ws/dm32/ja/qmill-001" />
    </url>
    <url>
    <loc>https://missav.ws/dm31/emoi-020</loc>
    <xhtml:link rel="alternate" hreflang="en" href="https://missav.ws/dm31/en/emoi-020" />
    </url>
    <url>
    <loc>https://missav.ws/dm32/qmill-001</loc>
    <xhtml:link rel="alternate" hreflang="en" href="https://missav.ws/dm32/en/qmill-001" />
    </url>
    <url>
    <loc>https://missav.ws/dm32/not-a-video-page</loc>
    <xhtml:link rel="alternate" hreflang="en" href="https://missav.ws/dm32/en/not-a-video-page" />
    </url>
</urlset>"""

SAMPLE_ITEMS_XML_2 = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:xhtml="http://www.w3.org/1999/xhtml">
    <url>
    <loc>https://missav.ws/dm30/ssis-123</loc>
    <xhtml:link rel="alternate" hreflang="en" href="https://missav.ws/dm30/en/ssis-123" />
    </url>
</urlset>"""

SAMPLE_VIDEO_HTML = """<!DOCTYPE html>
<html lang="en"><head>
<meta property="og:title" content="QMILL-001 A First Time Story" />
<meta property="og:image" content="https://fourho.com/cover/qmill-001.jpg" />
<meta property="og:video:release_date" content="2026-07-06" />
<meta property="og:video:duration" content="7200" />
<meta name="keywords" content="Big Breasts, Married Woman, Drama" />
</head><body><h1>QMILL-001</h1></body></html>"""


class TestSitemapParsing(unittest.TestCase):
    def test_index_puts_items_first(self):
        locs = mv.parse_sitemap_index(SAMPLE_INDEX_XML)
        self.assertEqual(locs[0], "https://missav.ws/sitemap_items_1.xml")
        self.assertEqual(locs[1], "https://missav.ws/sitemap_items_2.xml")
        self.assertEqual(len(locs), 4)

    def test_items_yields_en_url_and_code_in_order(self):
        videos = mv.parse_items_sitemap(SAMPLE_ITEMS_XML)
        self.assertEqual(videos, [
            ("https://missav.ws/dm32/en/qmill-001", "qmill-001"),
            ("https://missav.ws/dm31/en/emoi-020", "emoi-020"),
        ])

    def test_items_dedupes_repeat_code_and_skips_non_code(self):
        videos = mv.parse_items_sitemap(SAMPLE_ITEMS_XML)
        codes = [c for _, c in videos]
        self.assertEqual(len(codes), len(set(codes)))
        self.assertNotIn("not-a-video-page", codes)


class TestCodeFromUrl(unittest.TestCase):
    def test_en_and_default_paths(self):
        self.assertEqual(mv.code_from_url("https://missav.ws/dm32/en/qmill-001"), "qmill-001")
        self.assertEqual(mv.code_from_url("https://missav.ws/dm32/ssis-123"), "ssis-123")
        self.assertEqual(mv.code_from_url("https://missav.ws/dm31/en/emoi-020/"), "emoi-020")

    def test_non_code_returns_none(self):
        self.assertIsNone(mv.code_from_url("https://missav.ws/dm32/en/not-a-video-page"))
        self.assertIsNone(mv.code_from_url("https://missav.ws/"))
        self.assertIsNone(mv.code_from_url(""))


class TestBuildRecord(unittest.TestCase):
    def test_stub_carries_code_title_and_bridge(self):
        rec = mv.build_record("https://missav.ws/dm32/en/qmill-001", "qmill-001")
        self.assertEqual(rec["canonical_key"], "missav-qmill-001")
        self.assertEqual(rec["title"], "QMILL-001")
        self.assertEqual(rec["clean_title"], "QMILL-001")
        self.assertEqual(rec["slug"], "qmill-001")
        self.assertEqual(rec["url"], "https://missav.ws/dm32/en/qmill-001")
        self.assertEqual(rec["source_site"], "missav")
        self.assertEqual(len(rec["releases"]), 1)
        src = rec["releases"][0]["sources"][0]
        self.assertEqual(src["source_url"], "https://missav.ws/dm32/en/qmill-001")
        self.assertEqual(src["final_url"], "https://missav.ws/dm32/en/qmill-001")
        self.assertEqual(src["playback_type"], "url")
        self.assertEqual(src["status"], "unverified")

    def test_every_record_flagged_adult(self):
        for code in ("qmill-001", "ssis-123", "emoi-020"):
            rec = mv.build_record("https://missav.ws/dm32/en/%s" % code, code)
            self.assertEqual(rec["is_18_plus"], 1, code)

    def test_enrichment_upgrades_title_poster_and_year(self):
        enriched = mv.parse_video_page(SAMPLE_VIDEO_HTML)
        rec = mv.build_record("https://missav.ws/dm32/en/qmill-001", "qmill-001", enriched)
        self.assertEqual(rec["title"], "QMILL-001 A First Time Story")
        self.assertEqual(rec["poster_url"], "https://fourho.com/cover/qmill-001.jpg")
        self.assertEqual(rec["year"], 2026)
        self.assertEqual(rec["release_date"], "2026-07-06")
        self.assertEqual(rec["duration"], "7200")
        self.assertIn("Big Breasts", rec["genres"])
        self.assertEqual(rec["is_18_plus"], 1)


class TestSiteAuthority(unittest.TestCase):
    def test_neutral_code_is_adult_by_site_authority(self):
        self.assertEqual(
            fast_fetch.is_adult_title("QMILL-001", source_site="missav"), 1)
        self.assertEqual(
            fast_fetch.is_adult_title("QMILL-001", source_site="rogmovies"), 0)

    def test_missav_in_adult_source_sites(self):
        self.assertIn("missav", fast_fetch.ADULT_SOURCE_SITES)


class TestVideoPageParse(unittest.TestCase):
    def test_opengraph_fields(self):
        parsed = mv.parse_video_page(SAMPLE_VIDEO_HTML)
        self.assertEqual(parsed["title"], "QMILL-001 A First Time Story")
        self.assertEqual(parsed["poster_url"], "https://fourho.com/cover/qmill-001.jpg")
        self.assertEqual(parsed["release_date"], "2026-07-06")
        self.assertEqual(parsed["year"], 2026)
        self.assertEqual(parsed["duration"], "7200")
        self.assertIn("Drama", parsed["keywords"])

    def test_empty_page_returns_nones(self):
        parsed = mv.parse_video_page("")
        self.assertIsNone(parsed["title"])
        self.assertIsNone(parsed["poster_url"])
        self.assertIsNone(parsed["year"])


class TestSaveAndVerify(unittest.TestCase):
    def test_saved_rows_all_flagged_and_verified(self):
        recs = [mv.build_record("https://missav.ws/dm32/en/%s" % c, c)
                for c in ("qmill-001", "emoi-020")]
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "missav.db"
            totals = mv.export_staging(db_path, posts=recs)
            self.assertEqual(totals["posts_written"], 2)
            self.assertEqual(totals["releases_written"], 2)
            self.assertEqual(totals["sources_written"], 2)
            ok, result = mv.verify_db(db_path)
            self.assertTrue(ok, result)
            self.assertEqual(result["flagged_18_plus"], 2)
            self.assertEqual(result["posts"], 2)
            self.assertEqual(result["posts_without_release"], 0)
            self.assertEqual(result["sources_without_final_url"], 0)

    def test_reexport_is_idempotent(self):
        rec = mv.build_record("https://missav.ws/dm32/en/qmill-001", "qmill-001")
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "missav.db"
            mv.export_staging(db_path, posts=[rec])
            mv.export_staging(db_path, posts=[rec])
            result = mv.stats(db_path)
            self.assertEqual(result["posts"], 1)
            self.assertEqual(result["sources"], 1)


class TestSyncWithFakeFetcher(unittest.TestCase):
    def _fake(self, mapping):
        def fetch(url, timeout=30):
            for key, value in mapping.items():
                if key in url:
                    return value
            return (404, "")
        return fetch

    def test_sync_stages_from_sitemap_only(self):
        mapping = {
            "sitemap.xml": (200, SAMPLE_INDEX_XML),
            "sitemap_items_1.xml": (200, SAMPLE_ITEMS_XML),
            "sitemap_items_2.xml": (200, SAMPLE_ITEMS_XML_2),
        }
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "missav.db"
            totals = mv.sync(db_path=db_path, limit=5, base_url="https://missav.ws",
                             delay=0, fetcher=self._fake(mapping))
            self.assertEqual(totals["posts_written"], 3)
            self.assertEqual(totals["sitemaps_fetched"], 2)
            result = mv.stats(db_path)
            self.assertEqual(result["posts"], 3)
            self.assertEqual(result["flagged_18_plus"], 3)
            # Both files were fully processed (3 videos < limit 5), so both are marked.
            self.assertEqual(result["sitemaps_done"], 2)

    def test_sync_resumes_skipping_done_sitemap(self):
        mapping = {
            "sitemap.xml": (200, SAMPLE_INDEX_XML),
            "sitemap_items_1.xml": (200, SAMPLE_ITEMS_XML),
            "sitemap_items_2.xml": (200, SAMPLE_ITEMS_XML_2),
        }
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "missav.db"
            first = mv.sync(db_path=db_path, limit=5, base_url="https://missav.ws",
                            delay=0, fetcher=self._fake(mapping))
            second = mv.sync(db_path=db_path, limit=5, base_url="https://missav.ws",
                             delay=0, fetcher=self._fake(mapping))
            # Second run re-walks the index but both files are done: nothing new.
            self.assertEqual(first["posts_written"], 3)
            self.assertEqual(second["posts_written"], 0)
            self.assertEqual(mv.stats(db_path)["posts"], 3)

    def test_sync_limit_mid_file_leaves_it_unmarked(self):
        mapping = {
            "sitemap.xml": (200, SAMPLE_INDEX_XML),
            "sitemap_items_1.xml": (200, SAMPLE_ITEMS_XML),
        }
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "missav.db"
            totals = mv.sync(db_path=db_path, limit=1, base_url="https://missav.ws",
                             delay=0, fetcher=self._fake(mapping))
            self.assertEqual(totals["posts_written"], 1)
            self.assertEqual(mv.stats(db_path)["sitemaps_done"], 0)

    def test_enrich_keeps_stub_when_page_403s(self):
        mapping = {
            "sitemap.xml": (200, SAMPLE_INDEX_XML),
            "sitemap_items_1.xml": (200, SAMPLE_ITEMS_XML),
            "qmill-001": (403, ""),
            "emoi-020": (403, ""),
        }
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "missav.db"
            totals = mv.sync(db_path=db_path, limit=5, base_url="https://missav.ws",
                             delay=0, fetcher=self._fake(mapping), enrich=True)
            self.assertEqual(totals["posts_written"], 2)
            self.assertEqual(totals["pages_failed"], 2)
            self.assertEqual(totals["pages_enriched"], 0)
            with sqlite3.connect(str(db_path)) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT title, poster_url, is_18_plus FROM posts"
                    " WHERE canonical_key = 'missav-qmill-001'").fetchone()
            self.assertEqual(row["title"], "QMILL-001")
            self.assertIsNone(row["poster_url"])
            self.assertEqual(row["is_18_plus"], 1)


class TestRegistry(unittest.TestCase):
    def test_registry_entry_is_adult_scrape_only(self):
        reg_path = Path(__file__).parent.parent / "domain_registry.json"
        reg = json.loads(reg_path.read_text())
        entry = reg["sites"]["missav"]
        self.assertEqual(entry["active_base_url"], "https://missav.ws")
        self.assertIn("18+", entry.get("notes", ""))
        self.assertIn("never publish", entry.get("notes", ""))


if __name__ == "__main__":
    unittest.main(verbosity=2)
