#!/usr/bin/env python3
"""
test_xprimehub_import.py — Unit tests for the XprimeHub importer (Session 104).

Tests:
  1. Post parsing: nexdrive bridge extracted, quality from the title.
  2. Adult flag: EVERY row is_18_plus = 1, even for a title with no adult token
     (site authority via fast_fetch.ADULT_SOURCE_SITES + the importer's own assert).
  3. Save path: a saved row in a temp staging DB carries the flag.
  4. Sitemap sync: index -> post-sitemap1..5 locs land in sitemap_cache.
  5. Registry: the xprimehub entry exists with the live base and the 18+ note.

100% Python Standard Library. Zero external dependencies. Offline — temp SQLite
files only, no network, no catalog read.
"""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

import fast_fetch
import import_xprimehub

SAMPLE_XP_POST_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Stuck Analphoria 2026 English Adult Short Film 720p Download - XprimeHub</title>
    <meta property="og:image" content="https://xprimehub.pics/wp-content/uploads/2026/11/stuck-analphoria-poster.jpg">
</head>
<body>
    <h1>Stuck Analphoria 2026 English Adult Short Film 720p Download</h1>
    <div class="entry-content">
        <p><strong>Storyline:</strong> A short adult drama.</p>
        <p><a href="https://nexdrive.beer/genxfm_xp_001/">\u26a1 Download Now \u26a1</a></p>
    </div>
</body>
</html>
"""

SAMPLE_XP_NEUTRAL_HTML = """
<!DOCTYPE html>
<html>
<head><title>Midnight Web Series S01 2026 Hindi 720p Download - XprimeHub</title></head>
<body>
    <h1>Midnight Web Series S01 2026 Hindi 720p Download</h1>
    <div class="entry-content">
        <p><a href="https://nexdrive.beer/genxfm_xp_002/">\u26a1 Download Now \u26a1</a></p>
    </div>
</body>
</html>
"""


class TestXprimeHubExtract(unittest.TestCase):
    def test_post_parses_nexdrive_bridge(self):
        data = import_xprimehub.extract_post_data_xprimehub(
            "https://xprimehub.pics/stuck-analphoria-2026-english-adult-short-film-720p-download/",
            SAMPLE_XP_POST_HTML,
            resolve_bridges=False,
        )
        self.assertIsNotNone(data)
        self.assertEqual(data["source_site"], "xprimehub")
        self.assertEqual(len(data["releases"]), 1)
        rel = data["releases"][0]
        self.assertEqual(rel["quality"], "720p")
        self.assertEqual(rel["sources"][0]["service"], "nexdrive")
        self.assertEqual(rel["sources"][0]["source_url"], "https://nexdrive.beer/genxfm_xp_001/")

    def test_every_row_flagged_adult_even_without_adult_token(self):
        # The neutral title carries NO adult token: only site authority may flag it.
        self.assertEqual(fast_fetch.is_adult_title("Midnight Web Series S01 2026 Hindi"), 0)
        data = import_xprimehub.extract_post_data_xprimehub(
            "https://xprimehub.pics/midnight-web-series-s01-2026-hindi-720p-download/",
            SAMPLE_XP_NEUTRAL_HTML,
            resolve_bridges=False,
        )
        self.assertIsNotNone(data)
        self.assertEqual(data["is_18_plus"], 1)

    def test_site_authority_flags_neutral_title(self):
        self.assertEqual(
            fast_fetch.is_adult_title("Midnight Web Series S01", source_site="xprimehub"), 1)
        self.assertEqual(
            fast_fetch.is_adult_title("Midnight Web Series S01", source_site="rogmovies"), 0)


class TestXprimeHubSave(unittest.TestCase):
    def test_saved_row_carries_flag_in_staging_db(self):
        data = import_xprimehub.extract_post_data_xprimehub(
            "https://xprimehub.pics/midnight-web-series-s01-2026-hindi-720p-download/",
            SAMPLE_XP_NEUTRAL_HTML,
            resolve_bridges=False,
        )
        self.assertIsNotNone(data)
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "xprimehub.db"
            fast_fetch.DB_PATH = db_path
            fast_fetch.init_db()
            post_id = import_xprimehub.save_post_record(data, db_path)
            self.assertGreater(post_id, 0)
            with sqlite3.connect(str(db_path)) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT is_18_plus, source_site FROM posts WHERE id = ?", (post_id,)
                ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["is_18_plus"], 1)
            self.assertEqual(row["source_site"], "xprimehub")


class TestXprimeHubSitemap(unittest.TestCase):
    def test_sync_reads_index_then_sub_sitemaps(self):
        index_xml = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex><sitemap><loc>https://xprimehub.pics/post-sitemap1.xml</loc></sitemap>
<sitemap><loc>https://xprimehub.pics/post-sitemap2.xml</loc></sitemap></sitemapindex>"""
        sub_xml = """<?xml version="1.0" encoding="UTF-8"?>
<urlset><url><loc>https://xprimehub.pics/midnight-web-series-s01-2026-hindi-720p-download/</loc></url>
<url><loc>https://xprimehub.pics/category/adult/</loc></url></urlset>"""
        client = MagicMock()
        client.base_url = "https://xprimehub.pics"
        client.get_text.side_effect = [
            (200, "https://xprimehub.pics/sitemap.xml", index_xml),
            (200, "https://xprimehub.pics/post-sitemap1.xml", sub_xml),
            (200, "https://xprimehub.pics/post-sitemap2.xml", sub_xml),
        ]
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "xprimehub.db"
            n = import_xprimehub.sync_sitemap_to_db(client, db_path)
            self.assertEqual(n, 1)
            with sqlite3.connect(str(db_path)) as conn:
                rows = conn.execute(
                    "SELECT loc, site FROM sitemap_cache WHERE site = 'xprimehub'"
                ).fetchall()
            self.assertEqual(len(rows), 1)
            self.assertIn("midnight-web-series", rows[0][0])


class TestXprimeHubRegistry(unittest.TestCase):
    def test_registry_entry_is_adult_scrape_only(self):
        reg_path = Path(__file__).parent / "domain_registry.json"
        reg = json.loads(reg_path.read_text())
        entry = reg["sites"]["xprimehub"]
        self.assertEqual(entry["active_base_url"], "https://xprimehub.pics")
        self.assertIn("18+", entry.get("notes", ""))
        self.assertIn("never publish", entry.get("notes", ""))


if __name__ == "__main__":
    unittest.main(verbosity=2)
