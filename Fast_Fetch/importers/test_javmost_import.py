#!/usr/bin/env python3
"""
test_javmost_import.py — offline unit tests for the JAVMost importer.

No test touches the network: every fetch is a fake and every fixture is shaped
from pages measured live on 2026-11-11 (the sitemap index + movies-sitemap1
probe and the DLDSS-570 video page, from the Oracle VM and a real browser).
The rules this suite keeps, and the measured fact each one exists because of:

* javmost.ws is NOT Cloudflare-walled: homepage 200, video pages 200, from
  curl and from a real browser. MissAV (.live/.ws) and SupJav are walled even
  in a real browser; JavGuru is dead. JAVMost is the one JAV site that loads.
* The sitemap index is /sitemap_index.xml (robots.txt advertises it): 41
  entries, 34 movies-sitemapN.xml files (movies-sitemap1..34) plus
  page-sitemap.xml and others. Each movies file holds up to ~10,000 video
  URLs. A <url> block carries <loc>, <lastmod> and an <image:image> poster —
  so the sitemap alone stages REAL posters (MissAV's sitemap cannot).
* A video URL is /<CODE>-<VARIANT>/ — the code is the LEADING
  [A-Za-z]{2,6}-\\d{2,5} (DLDSS-570) and the variant is the rest
  (REDUCING-MOSAIC, UNCENSORED-EDIT). The same code can appear under several
  variants; the code is the work identity (canonical_key javmost-<code>).
* A video page carries og:title (with a "Genre:" list), og:image poster, a
  keywords meta tag (code, the real title in double quotes, a description,
  then " - " + actress + comma-separated genre tags) and a JSON-LD
  VideoObject (uploadDate). The player is JS-loaded (voe.sx embed); NO direct
  m3u8/mp4 is in the page, so the source stays a bridge-only unverified URL.
  The JSON-LD duration (PT7800M) is implausible and is NOT parsed.
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
import import_javmost as jm  # noqa: E402

SAMPLE_INDEX_XML = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <sitemap><loc>https://www.javmost.ws/page-sitemap.xml</loc></sitemap>
    <sitemap><loc>https://www.javmost.ws/movies-sitemap1.xml</loc></sitemap>
    <sitemap><loc>https://www.javmost.ws/movies-sitemap2.xml</loc></sitemap>
    <sitemap><loc>https://www.javmost.ws/actresses-sitemap1.xml</loc></sitemap>
</sitemapindex>"""

# Shaped from the real movies-sitemap1.xml (2026-11-11): one <url> per video,
# <loc> + <lastmod> + <image:image> poster. Includes a bare-code slug, a
# repeat code under a second variant (deduped), and the homepage (skipped).
SAMPLE_MOVIES_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">
    <url>
    <loc>https://www.javmost.ws/</loc>
    </url>
    <url>
    <lastmod>2026-11-10T03:02:54+00:00</lastmod>
    <loc>https://www.javmost.ws/DLDSS-570-REDUCING-MOSAIC/</loc>
    <image:image>
    <image:loc>https://img2.javmost.com/file_image/DLDSS-570-REDUCING-MOSAIC.jpg</image:loc>
    <image:title><![CDATA[DLDSS-570-REDUCING-MOSAIC.jpg]]></image:title>
    </image:image>
    </url>
    <url>
    <lastmod>2026-11-10T03:02:03+00:00</lastmod>
    <loc>https://www.javmost.ws/MILK-310-REDUCING-MOSAIC/</loc>
    <image:image>
    <image:loc>https://img2.javmost.com/file_image/MILK-310-REDUCING-MOSAIC.jpg</image:loc>
    <image:title><![CDATA[MILK-310-REDUCING-MOSAIC.jpg]]></image:title>
    </image:image>
    </url>
    <url>
    <lastmod>2026-11-09T02:01:00+00:00</lastmod>
    <loc>https://www.javmost.ws/SDNM-538/</loc>
    <image:image>
    <image:loc>https://img2.javmost.com/file_image/SDNM-538.jpg</image:loc>
    <image:title><![CDATA[SDNM-538.jpg]]></image:title>
    </image:image>
    </url>
    <url>
    <lastmod>2026-11-09T02:00:00+00:00</lastmod>
    <loc>https://www.javmost.ws/SDNM-538-UNCENSORED-EDIT/</loc>
    <image:image>
    <image:loc>https://img2.javmost.com/file_image/SDNM-538-UNCENSORED-EDIT.jpg</image:loc>
    <image:title><![CDATA[SDNM-538-UNCENSORED-EDIT.jpg]]></image:title>
    </image:image>
    </url>
</urlset>"""

SAMPLE_MOVIES_XML_2 = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">
    <url>
    <lastmod>2026-11-10T03:01:00+00:00</lastmod>
    <loc>https://www.javmost.ws/SSIS-123-REDUCING-MOSAIC/</loc>
    <image:image>
    <image:loc>https://img2.javmost.com/file_image/SSIS-123-REDUCING-MOSAIC.jpg</image:loc>
    <image:title><![CDATA[SSIS-123-REDUCING-MOSAIC.jpg]]></image:title>
    </image:image>
    </url>
</urlset>"""

# Shaped from the real DLDSS-570 video page (2026-11-11): og tags, the
# keywords meta (code, quoted real title, description, " - " + actress +
# genre tags) and the JSON-LD VideoObject with uploadDate.
SAMPLE_VIDEO_HTML = """<!DOCTYPE html>
<html lang="en"><head>
<title>DLDSS-570-REDUCING-MOSAIC - Watch JAV Online Free Streaming | JAVMOST</title>
<meta property="og:title" content="Watch DLDSS-570-REDUCING-MOSAIC JAV movie online free streaming. Genre: Mother, Virgin. Full HD Japanese porn video." />
<meta property="og:image" content="https://img2.javmost.ws/file_image/DLDSS-570-REDUCING-MOSAIC.jpg" />
<meta property="og:url" content="https://www.javmost.ws/DLDSS-570-REDUCING-MOSAIC/" />
<meta property="og:type" content="video" />
<meta name="keywords" content="DLDSS-570-REDUCING-MOSAIC, &quot;I Want To Protect My Daughter's Virginity...&quot; Her Mother Always Leaves Me Feeling Empty Inside, Refusing To Let Me Have Sex With Her Daughter. - Koizumi Kumi,Creampie,Solowork,Big Tits,Married Woman,Mature Woman,Cuckold" />
<script type="application/ld+json">
{
 "@context": "https://schema.org",
 "@type": "VideoObject",
 "name": "DLDSS-570-REDUCING-MOSAIC",
 "description": "Watch DLDSS-570-REDUCING-MOSAIC JAV movie online streaming.",
 "thumbnailUrl": "https://img2.javmost.ws/file_image/DLDSS-570-REDUCING-MOSAIC.jpg",
 "uploadDate": "2026-03-03",
 "duration": "PT7800M",
 "contentUrl": "https://www.javmost.ws/DLDSS-570-REDUCING-MOSAIC/"
}
</script>
</head><body><h1>DLDSS-570-REDUCING-MOSAIC</h1></body></html>"""


class TestSitemapParsing(unittest.TestCase):
    def test_index_keeps_only_movies_files(self):
        locs = jm.parse_sitemap_index(SAMPLE_INDEX_XML)
        self.assertEqual(locs, [
            "https://www.javmost.ws/movies-sitemap1.xml",
            "https://www.javmost.ws/movies-sitemap2.xml",
        ])

    def test_movies_yields_url_code_poster_variant_in_order(self):
        videos = jm.parse_movies_sitemap(SAMPLE_MOVIES_XML)
        self.assertEqual(videos, [
            ("https://www.javmost.ws/DLDSS-570-REDUCING-MOSAIC/", "dldss-570",
             "https://img2.javmost.com/file_image/DLDSS-570-REDUCING-MOSAIC.jpg",
             "REDUCING-MOSAIC"),
            ("https://www.javmost.ws/MILK-310-REDUCING-MOSAIC/", "milk-310",
             "https://img2.javmost.com/file_image/MILK-310-REDUCING-MOSAIC.jpg",
             "REDUCING-MOSAIC"),
            ("https://www.javmost.ws/SDNM-538/", "sdnm-538",
             "https://img2.javmost.com/file_image/SDNM-538.jpg", None),
        ])

    def test_movies_dedupes_repeat_code_and_skips_homepage(self):
        videos = jm.parse_movies_sitemap(SAMPLE_MOVIES_XML)
        codes = [c for _, c, _, _ in videos]
        self.assertEqual(len(codes), len(set(codes)))
        self.assertNotIn("SDNM-538-UNCENSORED-EDIT", [u for u, _, _, _ in videos])
        self.assertEqual(len(videos), 3)


class TestCodeFromUrl(unittest.TestCase):
    def test_leading_code_and_variant(self):
        self.assertEqual(
            jm.code_from_url("https://www.javmost.ws/DLDSS-570-REDUCING-MOSAIC/"),
            ("dldss-570", "REDUCING-MOSAIC"))
        self.assertEqual(
            jm.code_from_url("https://www.javmost.ws/SDNM-538-UNCENSORED-EDIT/"),
            ("sdnm-538", "UNCENSORED-EDIT"))

    def test_bare_code_has_no_variant(self):
        self.assertEqual(
            jm.code_from_url("https://www.javmost.ws/SDNM-538/"),
            ("sdnm-538", None))

    def test_non_code_returns_none_none(self):
        self.assertEqual(jm.code_from_url("https://www.javmost.ws/"), (None, None))
        self.assertEqual(jm.code_from_url("https://www.javmost.ws/not-a-video/"),
                         (None, None))
        self.assertEqual(jm.code_from_url(""), (None, None))


class TestBuildRecord(unittest.TestCase):
    def test_stub_carries_code_title_sitemap_poster_and_bridge(self):
        rec = jm.build_record(
            "https://www.javmost.ws/DLDSS-570-REDUCING-MOSAIC/", "dldss-570",
            "https://img2.javmost.com/file_image/DLDSS-570-REDUCING-MOSAIC.jpg",
            "REDUCING-MOSAIC")
        self.assertEqual(rec["canonical_key"], "javmost-dldss-570")
        self.assertEqual(rec["title"], "DLDSS-570")
        self.assertEqual(rec["clean_title"], "DLDSS-570")
        self.assertEqual(rec["slug"], "dldss-570")
        self.assertEqual(
            rec["poster_url"],
            "https://img2.javmost.com/file_image/DLDSS-570-REDUCING-MOSAIC.jpg")
        self.assertEqual(rec["url"], "https://www.javmost.ws/DLDSS-570-REDUCING-MOSAIC/")
        self.assertEqual(rec["source_site"], "javmost")
        self.assertEqual(rec["releases"][0]["label"], "JAVMost Reducing-Mosaic")
        self.assertEqual(rec["raw_meta"]["variant"], "REDUCING-MOSAIC")
        self.assertEqual(len(rec["releases"]), 1)
        src = rec["releases"][0]["sources"][0]
        self.assertEqual(src["source_url"], "https://www.javmost.ws/DLDSS-570-REDUCING-MOSAIC/")
        self.assertEqual(src["final_url"], "https://www.javmost.ws/DLDSS-570-REDUCING-MOSAIC/")
        self.assertEqual(src["playback_type"], "url")
        self.assertEqual(src["status"], "unverified")

    def test_every_record_flagged_adult(self):
        for code in ("dldss-570", "ssis-123", "milk-310"):
            rec = jm.build_record("https://www.javmost.ws/%s/" % code.upper(), code)
            self.assertEqual(rec["is_18_plus"], 1, code)

    def test_enrichment_upgrades_title_poster_year_cast_genres(self):
        enriched = jm.parse_video_page(SAMPLE_VIDEO_HTML)
        rec = jm.build_record(
            "https://www.javmost.ws/DLDSS-570-REDUCING-MOSAIC/", "dldss-570",
            "https://img2.javmost.com/file_image/DLDSS-570-REDUCING-MOSAIC.jpg",
            "REDUCING-MOSAIC", enriched)
        self.assertEqual(rec["title"], "I Want To Protect My Daughter's Virginity...")
        self.assertEqual(
            rec["poster_url"],
            "https://img2.javmost.ws/file_image/DLDSS-570-REDUCING-MOSAIC.jpg")
        self.assertEqual(rec["year"], 2026)
        self.assertEqual(rec["release_date"], "2026-03-03")
        self.assertEqual(rec["cast_names"], "Koizumi Kumi")
        self.assertIn("Creampie", rec["genres"])
        self.assertIn("Married Woman", rec["genres"])
        self.assertEqual(rec["is_18_plus"], 1)


class TestSiteAuthority(unittest.TestCase):
    def test_neutral_code_is_adult_by_site_authority(self):
        self.assertEqual(
            fast_fetch.is_adult_title("DLDSS-570", source_site="javmost"), 1)
        self.assertEqual(
            fast_fetch.is_adult_title("DLDSS-570", source_site="rogmovies"), 0)

    def test_javmost_in_adult_source_sites(self):
        self.assertIn("javmost", fast_fetch.ADULT_SOURCE_SITES)


class TestVideoPageParse(unittest.TestCase):
    def test_og_keywords_and_jsonld_fields(self):
        parsed = jm.parse_video_page(SAMPLE_VIDEO_HTML)
        self.assertEqual(parsed["title"], "I Want To Protect My Daughter's Virginity...")
        self.assertEqual(
            parsed["poster_url"],
            "https://img2.javmost.ws/file_image/DLDSS-570-REDUCING-MOSAIC.jpg")
        self.assertEqual(parsed["release_date"], "2026-03-03")
        self.assertEqual(parsed["year"], 2026)
        self.assertEqual(parsed["cast_names"], "Koizumi Kumi")
        self.assertIn("Creampie", parsed["genres"])
        # The JSON-LD duration (PT7800M) is implausible and is not parsed.
        self.assertIsNone(parsed["duration"])

    def test_empty_page_returns_nones(self):
        parsed = jm.parse_video_page("")
        self.assertIsNone(parsed["title"])
        self.assertIsNone(parsed["poster_url"])
        self.assertIsNone(parsed["year"])
        self.assertIsNone(parsed["cast_names"])
        self.assertIsNone(parsed["genres"])


class TestSaveAndVerify(unittest.TestCase):
    def test_saved_rows_all_flagged_with_posters_and_verified(self):
        recs = [jm.build_record(
            "https://www.javmost.ws/%s-REDUCING-MOSAIC/" % c.upper(), c,
            "https://img2.javmost.com/file_image/%s-REDUCING-MOSAIC.jpg" % c.upper(),
            "REDUCING-MOSAIC")
            for c in ("dldss-570", "milk-310")]
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "javmost.db"
            totals = jm.export_staging(db_path, posts=recs)
            self.assertEqual(totals["posts_written"], 2)
            self.assertEqual(totals["releases_written"], 2)
            self.assertEqual(totals["sources_written"], 2)
            ok, result = jm.verify_db(db_path)
            self.assertTrue(ok, result)
            self.assertEqual(result["flagged_18_plus"], 2)
            self.assertEqual(result["posts"], 2)
            self.assertEqual(result["posts_with_poster"], 2)
            self.assertEqual(result["posts_without_release"], 0)
            self.assertEqual(result["sources_without_final_url"], 0)

    def test_reexport_is_idempotent(self):
        rec = jm.build_record("https://www.javmost.ws/DLDSS-570-REDUCING-MOSAIC/",
                              "dldss-570", None, "REDUCING-MOSAIC")
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "javmost.db"
            jm.export_staging(db_path, posts=[rec])
            jm.export_staging(db_path, posts=[rec])
            result = jm.stats(db_path)
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

    def test_sync_stages_from_sitemap_only_with_posters(self):
        mapping = {
            "sitemap_index.xml": (200, SAMPLE_INDEX_XML),
            "movies-sitemap1.xml": (200, SAMPLE_MOVIES_XML),
            "movies-sitemap2.xml": (200, SAMPLE_MOVIES_XML_2),
        }
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "javmost.db"
            totals = jm.sync(db_path=db_path, limit=5, base_url="https://www.javmost.ws",
                             delay=0, fetcher=self._fake(mapping))
            self.assertEqual(totals["posts_written"], 4)
            self.assertEqual(totals["sitemaps_fetched"], 2)
            result = jm.stats(db_path)
            self.assertEqual(result["posts"], 4)
            self.assertEqual(result["flagged_18_plus"], 4)
            self.assertEqual(result["posts_with_poster"], 4)
            # Both files were fully processed (4 videos < limit 5), so both are marked.
            self.assertEqual(result["sitemaps_done"], 2)

    def test_sync_resumes_skipping_done_sitemap(self):
        mapping = {
            "sitemap_index.xml": (200, SAMPLE_INDEX_XML),
            "movies-sitemap1.xml": (200, SAMPLE_MOVIES_XML),
            "movies-sitemap2.xml": (200, SAMPLE_MOVIES_XML_2),
        }
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "javmost.db"
            first = jm.sync(db_path=db_path, limit=5, base_url="https://www.javmost.ws",
                            delay=0, fetcher=self._fake(mapping))
            second = jm.sync(db_path=db_path, limit=5, base_url="https://www.javmost.ws",
                             delay=0, fetcher=self._fake(mapping))
            # Second run re-walks the index but both files are done: nothing new.
            self.assertEqual(first["posts_written"], 4)
            self.assertEqual(second["posts_written"], 0)
            self.assertEqual(jm.stats(db_path)["posts"], 4)

    def test_sync_limit_mid_file_leaves_it_unmarked(self):
        mapping = {
            "sitemap_index.xml": (200, SAMPLE_INDEX_XML),
            "movies-sitemap1.xml": (200, SAMPLE_MOVIES_XML),
        }
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "javmost.db"
            totals = jm.sync(db_path=db_path, limit=1, base_url="https://www.javmost.ws",
                             delay=0, fetcher=self._fake(mapping))
            self.assertEqual(totals["posts_written"], 1)
            self.assertEqual(jm.stats(db_path)["sitemaps_done"], 0)

    def test_enrich_keeps_stub_when_page_403s(self):
        mapping = {
            "sitemap_index.xml": (200, SAMPLE_INDEX_XML),
            "movies-sitemap1.xml": (200, SAMPLE_MOVIES_XML),
            "DLDSS-570": (403, ""),
            "MILK-310": (403, ""),
            "SDNM-538": (403, ""),
        }
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "javmost.db"
            totals = jm.sync(db_path=db_path, limit=5, base_url="https://www.javmost.ws",
                             delay=0, fetcher=self._fake(mapping), enrich=True)
            self.assertEqual(totals["posts_written"], 3)
            self.assertEqual(totals["pages_failed"], 3)
            self.assertEqual(totals["pages_enriched"], 0)
            with sqlite3.connect(str(db_path)) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT title, poster_url, is_18_plus FROM posts"
                    " WHERE canonical_key = 'javmost-dldss-570'").fetchone()
            # Stub keeps the code title but the SITEMAP poster still stands.
            self.assertEqual(row["title"], "DLDSS-570")
            self.assertEqual(
                row["poster_url"],
                "https://img2.javmost.com/file_image/DLDSS-570-REDUCING-MOSAIC.jpg")
            self.assertEqual(row["is_18_plus"], 1)

    def test_enrich_upgrades_stub_when_page_loads(self):
        mapping = {
            "sitemap_index.xml": (200, SAMPLE_INDEX_XML),
            "movies-sitemap1.xml": (200, SAMPLE_MOVIES_XML),
            "DLDSS-570": (200, SAMPLE_VIDEO_HTML),
            "MILK-310": (403, ""),
            "SDNM-538": (403, ""),
        }
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "javmost.db"
            totals = jm.sync(db_path=db_path, limit=5, base_url="https://www.javmost.ws",
                             delay=0, fetcher=self._fake(mapping), enrich=True)
            self.assertEqual(totals["posts_written"], 3)
            self.assertEqual(totals["pages_enriched"], 1)
            with sqlite3.connect(str(db_path)) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT title, year, cast_names, is_18_plus FROM posts"
                    " WHERE canonical_key = 'javmost-dldss-570'").fetchone()
            self.assertEqual(row["title"], "I Want To Protect My Daughter's Virginity...")
            self.assertEqual(row["year"], 2026)
            self.assertEqual(row["cast_names"], "Koizumi Kumi")
            self.assertEqual(row["is_18_plus"], 1)


class TestRegistry(unittest.TestCase):
    def test_registry_entry_is_adult_scrape_only(self):
        reg_path = Path(__file__).parent.parent / "domain_registry.json"
        reg = json.loads(reg_path.read_text())
        entry = reg["sites"]["javmost"]
        self.assertEqual(entry["active_base_url"], "https://www.javmost.ws")
        self.assertIn("18+", entry.get("notes", ""))
        self.assertIn("never publish", entry.get("notes", ""))


if __name__ == "__main__":
    unittest.main(verbosity=2)
