#!/usr/bin/env python3
"""
test_moviesdrive_import.py — Unit tests for the MoviesDrive importer (Session 118).

Tests:
  1. Archive links: only mdrive.lol/archive/<id>/ links survive (Telegram,
     IMDb, mirror links are noise).
  2. Archive sources: hubcloud / gdflix anchors only, download playback.
  3. Post data: one release per archive link, quality/size/codec from the
     archive title, languages from the WP title.
  4. No archive links -> None; archives with no file host -> None.
  5. Language words helper.
  6. Save path: a saved post in a temp staging DB.
  7. Post sync: mocked wp-json pages -> sitemap_cache rows.
  8. Registry: the moviesdrive entry exists with the wp-json endpoint.

100% Python Standard Library. Zero external pip packages. Offline — temp SQLite
files only, no network, no catalog read. Fixture file-host URLs use the
reserved .test TLD; they exercise the mapping, never a real download link.
"""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

import fast_fetch
import import_moviesdrive

SAMPLE_MD_WP_POST = {
    "id": 65291,
    "slug": "wwe-crown-jewel-2026-2026-web-dl-hindi-dd2-0-english-480p-720p-1080p-x264-esubs-full-movie",
    "link": "https://new1.moviesdrive.cyou/wwe-crown-jewel-2026-2026-web-dl-hindi-dd2-0-english-480p-720p-1080p-x264-esubs-full-movie/",
    "title": {"rendered": "WWE Crown Jewel (2026) WEB-DL Hindi DD2.0 English 480p 720p 1080p x264 ESubs Full Movie"},
    "content": {"rendered": """
        <p><a href="https://moviesdrives.bid/">MoviesDrive</a></p>
        <p><a href="https://t.me/moviesdrivee">Telegram</a></p>
        <p><a href="https://www.imdb.com/title/tt44954660/">IMDb</a></p>
        <p><a href="https://mdrive.lol/archive/25388/">480p Download</a></p>
        <p><a href="https://mdrive.lol/archive/25387/">720p Download</a></p>
        <p><a href="https://mdrive.lol/archive/25388/">480p Download</a></p>
    """},
    "date": "2026-11-08T10:00:00",
}

SAMPLE_MD_ARCH_480_HTML = """
<!DOCTYPE html>
<html><head>
<title>WWE Crown Jewel (2026) WEB-DL [Hindi (DD2.0) &#038; English] 480p x264 [658.47 MB]</title>
</head><body>
<nav><a href="https://mdrive.lol/">Home</a></nav>
<p><a href="https://hubcloud.test/drive/dezdtvddj1zsmjs">Download 480p</a></p>
<p><a href="https://t.me/moviesdrivee">Telegram</a></p>
</body></html>
"""

SAMPLE_MD_ARCH_720_HTML = """
<!DOCTYPE html>
<html><head>
<title>WWE Crown Jewel (2026) WEB-DL [Hindi (DD2.0) &#038; English] 720p x264 [1.2 GB]</title>
</head><body>
<p><a href="https://gdflix.test/file/abc123">Download 720p</a></p>
</body></html>
"""

SAMPLE_MD_ARCH_NO_HOST_HTML = """
<!DOCTYPE html>
<html><head><title>Some Title (2026) 480p x264 [500 MB]</title></head>
<body><p><a href="https://mdrive.lol/">Home</a></p></body></html>
"""


class TestMoviesDriveExtract(unittest.TestCase):
    def test_archive_links_only_mdrive(self):
        links = import_moviesdrive.extract_archive_links(
            SAMPLE_MD_WP_POST["content"]["rendered"])
        self.assertEqual(links, [
            "https://mdrive.lol/archive/25388/",
            "https://mdrive.lol/archive/25387/",
        ])

    def test_archive_sources_hubcloud_only(self):
        sources = import_moviesdrive.extract_archive_sources(SAMPLE_MD_ARCH_480_HTML)
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]["service"], "hubcloud")
        self.assertEqual(sources[0]["playback_type"], "download")
        self.assertEqual(sources[0]["final_url"], "https://hubcloud.test/drive/dezdtvddj1zsmjs")

    def test_archive_sources_gdflix(self):
        sources = import_moviesdrive.extract_archive_sources(SAMPLE_MD_ARCH_720_HTML)
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]["service"], "gdflix")

    def test_post_data_one_release_per_archive(self):
        archive_pages = {
            "https://mdrive.lol/archive/25388/": SAMPLE_MD_ARCH_480_HTML,
            "https://mdrive.lol/archive/25387/": SAMPLE_MD_ARCH_720_HTML,
        }
        data = import_moviesdrive.extract_post_data_moviesdrive(SAMPLE_MD_WP_POST, archive_pages)
        self.assertIsNotNone(data)
        self.assertEqual(data["source_site"], "moviesdrive")
        self.assertEqual(data["year"], 2026)
        self.assertTrue(data["clean_title"].startswith("WWE Crown Jewel"))
        self.assertEqual(len(data["releases"]), 2)
        by_quality = {r["quality"]: r for r in data["releases"]}
        self.assertEqual(by_quality["480p"]["size"], "658.47 MB")
        self.assertEqual(by_quality["480p"]["codec"], "X264")
        self.assertEqual(by_quality["720p"]["size"], "1.2 GB")
        self.assertEqual(by_quality["480p"]["languages"], "Hindi + English")
        self.assertEqual(by_quality["480p"]["sources"][0]["service"], "hubcloud")
        self.assertEqual(by_quality["720p"]["sources"][0]["service"], "gdflix")

    def test_no_archive_links_is_none(self):
        post = dict(SAMPLE_MD_WP_POST)
        post["content"] = {"rendered": "<p>No links here</p>"}
        self.assertIsNone(import_moviesdrive.extract_post_data_moviesdrive(post, {}))

    def test_archives_without_file_host_is_none(self):
        archive_pages = {
            "https://mdrive.lol/archive/25388/": SAMPLE_MD_ARCH_NO_HOST_HTML,
            "https://mdrive.lol/archive/25387/": SAMPLE_MD_ARCH_NO_HOST_HTML,
        }
        self.assertIsNone(import_moviesdrive.extract_post_data_moviesdrive(SAMPLE_MD_WP_POST, archive_pages))

    def test_languages_from_title(self):
        self.assertEqual(
            import_moviesdrive.languages_from_title("Movie (2026) Hindi DD2.0 English 480p"),
            "Hindi + English")
        self.assertEqual(import_moviesdrive.languages_from_title("Scene (2026) Tamil"), "Tamil")
        self.assertEqual(import_moviesdrive.languages_from_title("No Language Here"), "")


class TestMoviesDriveSave(unittest.TestCase):
    def test_saved_post_in_staging_db(self):
        archive_pages = {
            "https://mdrive.lol/archive/25388/": SAMPLE_MD_ARCH_480_HTML,
            "https://mdrive.lol/archive/25387/": SAMPLE_MD_ARCH_720_HTML,
        }
        data = import_moviesdrive.extract_post_data_moviesdrive(SAMPLE_MD_WP_POST, archive_pages)
        self.assertIsNotNone(data)
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "moviesdrive.db"
            fast_fetch.DB_PATH = db_path
            fast_fetch.init_db()
            post_id = import_moviesdrive.save_post_record(data, db_path)
            self.assertGreater(post_id, 0)
            with sqlite3.connect(str(db_path)) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT source_site, content_type FROM posts WHERE id = ?", (post_id,)
                ).fetchone()
                n_rel = conn.execute("SELECT count(*) FROM releases WHERE post_id = ?", (post_id,)).fetchone()[0]
                n_src = conn.execute("SELECT count(*) FROM download_sources").fetchone()[0]
            self.assertEqual(row["source_site"], "moviesdrive")
            self.assertEqual(n_rel, 2)
            self.assertEqual(n_src, 2)


class TestMoviesDriveSync(unittest.TestCase):
    def test_sync_walks_wp_json_pages(self):
        client = MagicMock()
        client.wp_posts_page.side_effect = [
            ([SAMPLE_MD_WP_POST], 2),
            ([dict(SAMPLE_MD_WP_POST, id=65290, slug="scene-2026",
                   link="https://new1.moviesdrive.cyou/scene-2026/")], 2),
        ]
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "moviesdrive.db"
            n = import_moviesdrive.sync_posts_to_db(client, db_path)
            self.assertEqual(n, 2)
            with sqlite3.connect(str(db_path)) as conn:
                rows = conn.execute(
                    "SELECT loc, site FROM sitemap_cache WHERE site = 'moviesdrive'"
                ).fetchall()
            self.assertEqual(len(rows), 2)


class TestMoviesDriveRegistry(unittest.TestCase):
    def test_registry_entry_points_at_live_wp_json(self):
        reg_path = Path(__file__).parent / "domain_registry.json"
        reg = json.loads(reg_path.read_text())
        entry = reg["sites"]["moviesdrive"]
        self.assertEqual(entry["active_base_url"], "https://new1.moviesdrive.cyou")
        self.assertEqual(entry["api_type"], "wp_rest_api")
        self.assertEqual(entry["api_endpoint"], "/wp-json/wp/v2/posts")
        self.assertEqual(entry["status"], "active")


if __name__ == "__main__":
    unittest.main(verbosity=2)
