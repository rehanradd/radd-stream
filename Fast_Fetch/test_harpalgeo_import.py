#!/usr/bin/env python3
"""
test_harpalgeo_import.py — Unit tests for the HarPal Geo importer (Session 118).

Tests:
  1. Program links: homepage yields program links only (episode links excluded).
  2. Episode links: teaser links dropped, full episodes kept.
  3. Stream extraction: the 5centscdn playlist wins when two .m3u8s are present.
  4. Episode title parse: episode number + air date from the <title>.
  5. Program data: one series post, one release per full episode, direct HLS.
  6. No playable episode -> None.
  7. Save path: a saved program in a temp staging DB (posts/releases/sources).
  8. Program sync: mocked homepage -> sitemap_cache rows.
  9. Registry: the harpalgeo entry exists with the live base.

100% Python Standard Library. Zero external dependencies. Offline — temp SQLite
files only, no network, no catalog read. Fixture stream URLs use the reserved
.test TLD; they exercise the extractor's shape, never a real playlist.
"""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

import fast_fetch
import import_harpalgeo

SAMPLE_HG_HOME_HTML = """
<!DOCTYPE html>
<html><head><title>Home Har Pal Geo</title></head><body>
<a href="https://harpalgeo.tv/program/Bano">Bano</a>
<a href="https://harpalgeo.tv/program/Aik-Thi-Rania">Aik Thi Rania</a>
<a href="https://harpalgeo.tv/program/Bano/26866">Bano Episode 26</a>
<a href="https://harpalgeo.tv/program/Bano">Bano</a>
</body></html>
"""

SAMPLE_HG_PROGRAM_HTML = """
<!DOCTYPE html>
<html><head>
<title>Bano Episode, Bano Drama Cast, Bano Schedule, Bano OST</title>
<meta property="og:image" content="https://harpalgeo.tv/wp-content/uploads/bano-poster.jpg">
</head><body>
<a href="https://harpalgeo.tv/program/Bano/26866">Episode 26 | Haris Waheed - Hina Tariq</a>
<a href="https://harpalgeo.tv/program/Bano/26855">Episode 25 | Haris Waheed - Hina Tariq</a>
<a href="https://harpalgeo.tv/program/Bano/26865"><img title="Episode 26 Teaser - 7th November 2026 - HAR PAL GEO"></a>
</body></html>
"""

SAMPLE_HG_EP26_HTML = """
<!DOCTYPE html>
<html><head>
<title>Bano Episode 26 | Haris Waheed Hina Tariq Aqeel Yousaf |, Har Pal Geo Drama - 8th Nov 2026 - Watch Online</title>
<script src="https://harpalgeo.tv/videojs/video.min.js"></script>
</head><body>
<video class="video-js"><source src="https://vjgnbjkgo97y-hls-push.5centscdn.test/mp4/raw/131/132/fake_combined.smil/playlist.m3u8" type="application/x-mpegURL"></video>
<script>var alt = "https://othercdn.test/bano26/playlist.m3u8";</script>
</body></html>
"""

SAMPLE_HG_EP25_HTML = """
<!DOCTYPE html>
<html><head>
<title>Bano Episode 25 | Haris Waheed Hina Tariq Aqeel Yousaf |, Har Pal Geo Drama - 7th Nov 2026 - Watch Online</title>
</head><body>
<video class="video-js"><source src="https://vjgnbjkgo97y-hls-push.5centscdn.test/mp4/raw/131/132/fake25_combined.smil/playlist.m3u8" type="application/x-mpegURL"></video>
</body></html>
"""

SAMPLE_HG_EP_NO_STREAM_HTML = """
<!DOCTYPE html>
<html><head><title>Bano Episode 24 | Haris Waheed |, Har Pal Geo Drama - 6th Nov 2026 - Watch Online</title></head>
<body><p>Coming soon</p></body></html>
"""


class TestHarPalGeoExtract(unittest.TestCase):
    def test_homepage_yields_programs_not_episodes(self):
        programs = import_harpalgeo.extract_program_links(SAMPLE_HG_HOME_HTML)
        self.assertEqual(len(programs), 2)
        self.assertIn("https://harpalgeo.tv/program/Bano", programs)
        self.assertIn("https://harpalgeo.tv/program/Aik-Thi-Rania", programs)
        self.assertFalse(any("/26866" in p for p in programs))

    def test_episode_links_drop_teasers(self):
        eps = import_harpalgeo.extract_episode_links(SAMPLE_HG_PROGRAM_HTML)
        urls = [e["url"] for e in eps]
        self.assertEqual(len(urls), 2)
        self.assertIn("https://harpalgeo.tv/program/Bano/26866", urls)
        self.assertIn("https://harpalgeo.tv/program/Bano/26855", urls)
        self.assertNotIn("https://harpalgeo.tv/program/Bano/26865", urls)

    def test_stream_prefers_5centscdn_playlist(self):
        stream = import_harpalgeo.extract_episode_stream(SAMPLE_HG_EP26_HTML)
        self.assertIsNotNone(stream)
        self.assertIn("5centscdn.test", stream)
        self.assertTrue(stream.endswith("playlist.m3u8"))

    def test_stream_missing_when_no_m3u8(self):
        self.assertIsNone(import_harpalgeo.extract_episode_stream(SAMPLE_HG_EP_NO_STREAM_HTML))

    def test_episode_title_parse(self):
        info = import_harpalgeo.parse_episode_title(
            SAMPLE_HG_EP26_HTML, "https://harpalgeo.tv/program/Bano/26866")
        self.assertEqual(info["episode"], 26)
        self.assertEqual(info["air_date"], "8th Nov 2026")

    def test_program_data_one_release_per_episode(self):
        episode_pages = {
            "https://harpalgeo.tv/program/Bano/26866": SAMPLE_HG_EP26_HTML,
            "https://harpalgeo.tv/program/Bano/26855": SAMPLE_HG_EP25_HTML,
        }
        data = import_harpalgeo.extract_program_data_harpalgeo(
            "https://harpalgeo.tv/program/Bano", SAMPLE_HG_PROGRAM_HTML, episode_pages)
        self.assertIsNotNone(data)
        self.assertEqual(data["source_site"], "harpalgeo")
        self.assertEqual(data["content_type"], "series")
        self.assertEqual(data["clean_title"], "Bano")
        self.assertEqual(data["language"], "Urdu")
        self.assertEqual(len(data["releases"]), 2)
        eps = sorted(r["episode"] for r in data["releases"])
        self.assertEqual(eps, ["E25", "E26"])
        for rel in data["releases"]:
            self.assertEqual(rel["quality"], "720p")
            src = rel["sources"][0]
            self.assertEqual(src["service"], "5centscdn")
            self.assertEqual(src["playback_type"], "direct")
            self.assertTrue(src["final_url"].endswith("playlist.m3u8"))

    def test_program_with_no_playable_episode_is_none(self):
        episode_pages = {
            "https://harpalgeo.tv/program/Bano/26841": SAMPLE_HG_EP_NO_STREAM_HTML,
        }
        prog_html = SAMPLE_HG_PROGRAM_HTML.replace("26866", "26841").replace("26855", "26842")
        data = import_harpalgeo.extract_program_data_harpalgeo(
            "https://harpalgeo.tv/program/Bano", prog_html, episode_pages)
        self.assertIsNone(data)


class TestHarPalGeoSave(unittest.TestCase):
    def test_saved_program_in_staging_db(self):
        episode_pages = {
            "https://harpalgeo.tv/program/Bano/26866": SAMPLE_HG_EP26_HTML,
            "https://harpalgeo.tv/program/Bano/26855": SAMPLE_HG_EP25_HTML,
        }
        data = import_harpalgeo.extract_program_data_harpalgeo(
            "https://harpalgeo.tv/program/Bano", SAMPLE_HG_PROGRAM_HTML, episode_pages)
        self.assertIsNotNone(data)
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "harpalgeo.db"
            fast_fetch.DB_PATH = db_path
            fast_fetch.init_db()
            post_id = import_harpalgeo.save_post_record(data, db_path)
            self.assertGreater(post_id, 0)
            with sqlite3.connect(str(db_path)) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT source_site, content_type FROM posts WHERE id = ?", (post_id,)
                ).fetchone()
                n_rel = conn.execute("SELECT count(*) FROM releases WHERE post_id = ?", (post_id,)).fetchone()[0]
                n_src = conn.execute("SELECT count(*) FROM download_sources").fetchone()[0]
            self.assertEqual(row["source_site"], "harpalgeo")
            self.assertEqual(row["content_type"], "series")
            self.assertEqual(n_rel, 2)
            self.assertEqual(n_src, 2)


class TestHarPalGeoSync(unittest.TestCase):
    def test_sync_reads_homepage_programs(self):
        client = MagicMock()
        client.base_url = "https://www.harpalgeo.tv"
        client.get_text.return_value = (200, "https://www.harpalgeo.tv/", SAMPLE_HG_HOME_HTML)
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "harpalgeo.db"
            n = import_harpalgeo.sync_programs_to_db(client, db_path)
            self.assertEqual(n, 2)
            with sqlite3.connect(str(db_path)) as conn:
                rows = conn.execute(
                    "SELECT loc, site FROM sitemap_cache WHERE site = 'harpalgeo'"
                ).fetchall()
            self.assertEqual(len(rows), 2)


class TestHarPalGeoRegistry(unittest.TestCase):
    def test_registry_entry_points_at_live_base(self):
        reg_path = Path(__file__).parent / "domain_registry.json"
        reg = json.loads(reg_path.read_text())
        entry = reg["sites"]["harpalgeo"]
        self.assertEqual(entry["active_base_url"], "https://www.harpalgeo.tv")
        self.assertEqual(entry["api_type"], "homepage")
        self.assertEqual(entry["status"], "active")
        self.assertIn("5centscdn", entry.get("notes", ""))


if __name__ == "__main__":
    unittest.main(verbosity=2)
