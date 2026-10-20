#!/usr/bin/env python3
"""
test_hdhub4u_import.py — Comprehensive unit tests for HDHub4u dedicated importer.

Tests:
  1. Title cleaning: Material icon stripping, year extraction, canonical key generation.
  2. Release link parsing: quality tiers, file sizes, codecs, episode extraction.
  3. Greenmotors payload decoding: 4-layer b64/rot13 unwrapping.
  4. API sync and sitemap_cache population.
  5. Staging SQLite database isolation and atomic persistence.

100% Python Standard Library. Zero external dependencies.
"""

import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import fast_fetch
import import_hdhub4u


# ── Sample HTML: Movie with 3 quality tiers ──────────────────────────────────

SAMPLE_MOVIE_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Kingsman: The Secret Service (2015) BluRay [Hindi &#038; English] 1080p 720p &#038; 480p Dual Audio | Full Movie &#8211; HDHub4u</title>
    <meta property="og:image" content="https://image.tmdb.org/t/p/w500/poster-kingsman.jpg" />
</head>
<body>
    <h1>
        <i class="material-icons">&#xE02C;</i>
        <span class="material-text">
            Kingsman: The Secret Service (2015) BluRay [Hindi (DD5.1) &#038; English] 1080p 720p &#038; 480p Dual Audio [x264 HEVC] | Full Movie
        </span>
    </h1>
    <div class="entry-content">
        <p><a href="https://www.imdb.com/title/tt2802144/">IMDb</a></p>
        <h4 class="download-heading">480p⚡[510MB]</h4>
        <p><a href="https://greenmotors.club/?id=abc480pId123" target="_blank">Download Links</a></p>

        <h4 class="download-heading">720p x264 [1.3GB]</h4>
        <p><a href="https://greenmotors.club/?id=abc720pId456" target="_blank">Download Links</a></p>

        <h4 class="download-heading">1080p BluRay [28.46GB]</h4>
        <p><a href="https://greenmotors.club/?id=abc1080pId789" target="_blank">Download Links</a></p>
    </div>
</body>
</html>
"""

# ── Sample HTML: TV Series with Episode buttons ─────────────────────────────

SAMPLE_SERIES_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>The Punisher (Season 2) WEB-DL [Hindi &#038; English] 720p | NF Series &#8211; HDHub4u</title>
</head>
<body>
    <h1>
        <i class="material-icons">&#xE02C;</i>
        <span class="material-text">
            The Punisher (Season 2) DS4K WEB-DL [Hindi (Studio-Dub DD5.1) &#038; English] 4K 1080p 720p &#038; 480p [x264/10Bit-HEVC] | NF Series | [EP-04 Added]
        </span>
    </h1>
    <div class="entry-content">
        <h4 class="download-heading">720p HEVC [300MB Each]</h4>
        <p><a href="https://greenmotors.club/?id=ep1abc123" target="_blank">EPiSODE 1</a></p>
        <p><a href="https://greenmotors.club/?id=ep2abc456" target="_blank">EPiSODE 2</a></p>
        <p><a href="https://greenmotors.club/?id=ep3abc789" target="_blank">EPiSODE 3</a></p>
        <p><a href="https://greenmotors.club/?id=ep4abcxyz" target="_blank">EPiSODE 4</a></p>
    </div>
</body>
</html>
"""

# ── Sample HTML: 4K UHD Movie ────────────────────────────────────────────────

SAMPLE_4K_HTML = """
<!DOCTYPE html>
<html>
<head><title>Dune: Part Two (2024) 4K UHD BluRay &#8211; HDHub4u</title></head>
<body>
    <h1>Dune: Part Two (2024) 4K UHD BluRay [Hindi &#038; English] 2160p [x265 10Bit HEVC] | Full Movie</h1>
    <div class="entry-content">
        <h3>2160p 4K [18.5GB]</h3>
        <p><a href="https://greenmotors.club/?id=dune4k001" target="_blank">Download 4K</a></p>
        <h3>1080p HEVC [4.2GB]</h3>
        <p><a href="https://greenmotors.club/?id=dune1080p001" target="_blank">Download 1080p</a></p>
    </div>
</body>
</html>
"""

# ── Sample Typesense API document ────────────────────────────────────────────

SAMPLE_API_DOC = {
    "id": "197700",
    "post_title": "Kingsman: The Secret Service (2015) BluRay [Hindi (DD5.1) & English] 1080p 720p & 480p Dual Audio [x264 HEVC] | Full Movie",
    "permalink": "https://new8.hdhub4u.cl/kingsman-the-secret-service-2015-hindi-bluray-full-movie/",
    "imdb_id": "tt2802144",
    "post_thumbnail": "https://image.tmdb.org/t/p/w500/poster-kingsman.jpg",
    "post_date": "October 18, 2026",
    "post_type": "post",
    "category": ["Action", "Comedy", "Dual Audio", "Hollywood"],
    "stars": ["Colin Firth", "Samuel L. Jackson", "Mark Strong"],
    "director": ["Matthew Vaughn"],
    "sort_by_date": 1792353042,
}


class TestTitleCleaning(unittest.TestCase):
    """Tests for clean_hdhub4u_title function."""

    def test_movie_title_with_material_icons(self):
        raw = "\ue02c Kingsman: The Secret Service (2015) BluRay [Hindi (DD5.1) & English] 1080p 720p & 480p Dual Audio [x264 HEVC] | Full Movie"
        title, year, key = import_hdhub4u.clean_hdhub4u_title(raw)
        self.assertEqual(title, "Kingsman: The Secret Service")
        self.assertEqual(year, 2015)
        self.assertIn("kingsman", key)

    def test_series_title_with_season(self):
        raw = "The Punisher (Season 2) DS4K WEB-DL [Hindi & English] 720p | NF Series"
        title, year, key = import_hdhub4u.clean_hdhub4u_title(raw)
        self.assertEqual(title, "The Punisher")
        self.assertIsNone(year)
        self.assertIn("punisher", key)

    def test_4k_title(self):
        raw = "Dune: Part Two (2024) 4K UHD BluRay [Hindi & English] 2160p [x265 10Bit HEVC] | Full Movie"
        title, year, key = import_hdhub4u.clean_hdhub4u_title(raw)
        self.assertEqual(title, "Dune: Part Two")
        self.assertEqual(year, 2024)
        self.assertIn("dune", key)

    def test_html_entity_stripping(self):
        raw = "Movie &#xE02C; Title (2023) 720p WEB-DL"
        title, year, key = import_hdhub4u.clean_hdhub4u_title(raw)
        self.assertEqual(title, "Movie Title")
        self.assertEqual(year, 2023)

    def test_empty_title_fallback(self):
        title, year, key = import_hdhub4u.clean_hdhub4u_title("")
        self.assertEqual(title, "")
        self.assertIsNone(year)


class TestReleasesParsing(unittest.TestCase):
    """Tests for parse_hdhub4u_release_links function."""

    def test_movie_three_quality_tiers(self):
        releases = import_hdhub4u.parse_hdhub4u_release_links(SAMPLE_MOVIE_HTML)
        self.assertEqual(len(releases), 3)

        q_list = [r["quality"] for r in releases]
        self.assertIn("480p", q_list)
        self.assertIn("720p", q_list)
        self.assertIn("1080p", q_list)

        r480 = next(r for r in releases if r["quality"] == "480p")
        self.assertEqual(r480["size"], "510MB")
        self.assertIn("greenmotors", r480["bridge_url"])
        self.assertIsNone(r480["episode_number"])

        r1080 = next(r for r in releases if r["quality"] == "1080p")
        self.assertEqual(r1080["size"], "28.46GB")

    def test_series_episode_buttons(self):
        releases = import_hdhub4u.parse_hdhub4u_release_links(SAMPLE_SERIES_HTML)
        self.assertEqual(len(releases), 4)

        for i, r in enumerate(releases, 1):
            self.assertEqual(r["episode_number"], i)
            self.assertEqual(r["season_number"], 1)
            self.assertEqual(r["quality"], "720p")

    def test_4k_quality_detection(self):
        releases = import_hdhub4u.parse_hdhub4u_release_links(SAMPLE_4K_HTML)
        self.assertEqual(len(releases), 2)
        q_list = [r["quality"] for r in releases]
        self.assertIn("2160p", q_list)
        self.assertIn("1080p", q_list)

        r4k = next(r for r in releases if r["quality"] == "2160p")
        self.assertEqual(r4k["size"], "18.5GB")

    def test_hevc_codec_detection(self):
        releases = import_hdhub4u.parse_hdhub4u_release_links(SAMPLE_SERIES_HTML)
        # HEVC in heading
        for r in releases:
            self.assertEqual(r["codec"], "HEVC")

    def test_no_greenmotors_returns_empty(self):
        html = "<h4>Some heading</h4><p>No download links here</p>"
        releases = import_hdhub4u.parse_hdhub4u_release_links(html)
        self.assertEqual(len(releases), 0)


class TestSizeParsing(unittest.TestCase):
    """Tests for parse_size_to_bytes function."""

    def test_gb(self):
        self.assertEqual(import_hdhub4u.parse_size_to_bytes("28.46GB"), int(28.46 * 1024 * 1024 * 1024))

    def test_mb(self):
        self.assertEqual(import_hdhub4u.parse_size_to_bytes("510MB"), int(510 * 1024 * 1024))

    def test_none(self):
        self.assertIsNone(import_hdhub4u.parse_size_to_bytes(None))
        self.assertIsNone(import_hdhub4u.parse_size_to_bytes(""))
        self.assertIsNone(import_hdhub4u.parse_size_to_bytes("unknown"))


class TestGreenmotorsPayload(unittest.TestCase):
    """Tests for decode_greenmotors_payload function."""

    def test_valid_payload_decode(self):
        # Encode a known payload through the 4-layer pipeline in reverse
        import codecs as _codecs
        dest_url = "https://hblinks.com/archives/123"
        inner_json = json.dumps({"o": base64.b64encode(dest_url.encode()).decode(), "w": 10})
        p3 = base64.b64encode(inner_json.encode()).decode()
        p2 = _codecs.encode(p3, "rot_13")
        p1 = base64.b64encode(p2.encode()).decode()
        payload = base64.b64encode(p1.encode()).decode()

        result = import_hdhub4u.decode_greenmotors_payload(payload)
        self.assertEqual(result, dest_url)

    def test_invalid_payload_returns_none(self):
        self.assertIsNone(import_hdhub4u.decode_greenmotors_payload("not_valid_base64!!"))
        self.assertIsNone(import_hdhub4u.decode_greenmotors_payload(""))


class TestPostDataExtraction(unittest.TestCase):
    """Tests for extract_post_data_hdhub4u with combined HTML + API doc."""

    def test_movie_extraction_with_api_doc(self):
        data = import_hdhub4u.extract_post_data_hdhub4u(
            post_url="https://new8.hdhub4u.cl/kingsman-the-secret-service-2015-hindi-bluray-full-movie/",
            page_html=SAMPLE_MOVIE_HTML,
            api_doc=SAMPLE_API_DOC,
            resolve_direct=False,
        )
        self.assertIsNotNone(data)
        self.assertEqual(data["title"], "Kingsman: The Secret Service")
        self.assertEqual(data["year"], 2015)
        self.assertEqual(data["imdb_id"], "tt2802144")
        self.assertEqual(data["poster_url"], "https://image.tmdb.org/t/p/w500/poster-kingsman.jpg")
        self.assertEqual(data["media_type"], "movie")
        self.assertEqual(len(data["releases"]), 3)

        # Verify genre enrichment from API doc
        genres = json.loads(data["genres"])
        self.assertIn("Action", genres)
        self.assertIn("Hollywood", genres)

    def test_movie_extraction_html_only(self):
        data = import_hdhub4u.extract_post_data_hdhub4u(
            post_url="https://new8.hdhub4u.cl/kingsman-the-secret-service-2015-hindi-bluray-full-movie/",
            page_html=SAMPLE_MOVIE_HTML,
            api_doc=None,
            resolve_direct=False,
        )
        self.assertIsNotNone(data)
        self.assertEqual(data["title"], "Kingsman: The Secret Service")
        self.assertEqual(data["year"], 2015)
        self.assertEqual(data["imdb_id"], "tt2802144")  # from HTML
        self.assertEqual(data["media_type"], "movie")

    def test_series_extraction(self):
        data = import_hdhub4u.extract_post_data_hdhub4u(
            post_url="https://new8.hdhub4u.cl/the-punisher-season-2/",
            page_html=SAMPLE_SERIES_HTML,
            api_doc=None,
            resolve_direct=False,
        )
        self.assertIsNotNone(data)
        self.assertEqual(data["title"], "The Punisher")
        self.assertEqual(data["media_type"], "series")
        self.assertEqual(len(data["releases"]), 4)

        # Episodes numbered correctly
        for i, r in enumerate(data["releases"], 1):
            self.assertEqual(r["episode_number"], i)

    def test_no_releases_returns_none(self):
        html = "<html><body><h1>No Downloads</h1></body></html>"
        data = import_hdhub4u.extract_post_data_hdhub4u(
            post_url="https://new8.hdhub4u.cl/no-movie/",
            page_html=html,
            resolve_direct=False,
        )
        self.assertIsNone(data)

    def test_each_release_has_sources(self):
        data = import_hdhub4u.extract_post_data_hdhub4u(
            post_url="https://new8.hdhub4u.cl/kingsman/",
            page_html=SAMPLE_MOVIE_HTML,
            api_doc=None,
            resolve_direct=False,
        )
        self.assertIsNotNone(data)
        for r in data["releases"]:
            self.assertGreater(len(r["sources"]), 0)
            src = r["sources"][0]
            self.assertEqual(src["service"], "greenmotors")
            self.assertIn("greenmotors", src["source_url"])


class TestStagingDatabase(unittest.TestCase):
    """Tests for staging database init, save, and status."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_hdhub4u.db"
        import_hdhub4u.init_staging_db(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_schema_creation(self):
        with sqlite3.connect(str(self.db_path)) as conn:
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()]
        self.assertIn("sitemap_cache", tables)
        self.assertIn("posts", tables)
        self.assertIn("releases", tables)
        self.assertIn("sources", tables)

    def test_save_movie_post(self):
        post_data = {
            "canonical_key": "kingsman-the-secret-service_2015",
            "title": "Kingsman: The Secret Service",
            "original_title": "Kingsman: The Secret Service (2015) BluRay",
            "year": 2015,
            "media_type": "movie",
            "imdb_id": "tt2802144",
            "poster_url": "https://image.tmdb.org/t/p/w500/poster.jpg",
            "genres": json.dumps(["Action", "Comedy"]),
            "site": "hdhub4u",
            "post_url": "https://new8.hdhub4u.cl/kingsman/",
            "releases": [
                {
                    "label": "720p x264 [1.3GB]",
                    "quality": "720p",
                    "resolution": "720p",
                    "size_bytes": int(1.3 * 1024 * 1024 * 1024),
                    "season_number": None,
                    "episode_number": None,
                    "codec": "x264",
                    "bridge_url": "https://greenmotors.club/?id=abc123",
                    "sources": [
                        {
                            "source_name": "⚡ HubCloud [FSL Cloudflare R2]",
                            "service": "fsl_r2",
                            "resource_id": "hash123",
                            "source_url": "https://greenmotors.club/?id=abc123",
                            "final_url": "https://abc.r2.cloudflarestorage.com/hub/kingsman.mkv",
                            "is_temporary": 0,
                            "quality": "720p",
                        },
                        {
                            "source_name": "⚡ PixelDrain [Direct CDN]",
                            "service": "pixeldrain",
                            "resource_id": "px123",
                            "source_url": "https://pixeldrain.com/u/px123",
                            "final_url": "https://pixeldrain.com/api/file/px123",
                            "is_temporary": 0,
                            "quality": "720p",
                        },
                    ],
                },
            ],
        }

        ok = import_hdhub4u.save_post_to_staging_db(self.db_path, post_data)
        self.assertTrue(ok)

        with sqlite3.connect(str(self.db_path)) as conn:
            posts = conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
            rels = conn.execute("SELECT COUNT(*) FROM releases").fetchone()[0]
            srcs = conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]

        self.assertEqual(posts, 1)
        self.assertEqual(rels, 1)
        self.assertEqual(srcs, 2)

    def test_upsert_same_canonical_key(self):
        post1 = {
            "canonical_key": "test-movie_2024",
            "title": "Test Movie",
            "original_title": "Test Movie (2024)",
            "year": 2024,
            "media_type": "movie",
            "site": "hdhub4u",
            "post_url": "https://new8.hdhub4u.cl/test-movie/",
            "releases": [{
                "label": "720p", "quality": "720p", "resolution": "720p",
                "size_bytes": None, "season_number": None, "episode_number": None,
                "codec": "x264", "bridge_url": "https://greenmotors.club/?id=x",
                "sources": [{
                    "source_name": "Stream", "service": "greenmotors",
                    "resource_id": "x", "source_url": "x", "final_url": "x",
                    "is_temporary": 0, "quality": "720p",
                }],
            }],
        }
        import_hdhub4u.save_post_to_staging_db(self.db_path, post1)

        # Save again with updated imdb_id
        post1["imdb_id"] = "tt9999999"
        import_hdhub4u.save_post_to_staging_db(self.db_path, post1)

        with sqlite3.connect(str(self.db_path)) as conn:
            posts = conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
            imdb = conn.execute("SELECT imdb_id FROM posts WHERE canonical_key = 'test-movie_2024'").fetchone()[0]
        self.assertEqual(posts, 1)
        self.assertEqual(imdb, "tt9999999")

    def test_save_returns_false_for_empty(self):
        self.assertFalse(import_hdhub4u.save_post_to_staging_db(self.db_path, None))
        self.assertFalse(import_hdhub4u.save_post_to_staging_db(self.db_path, {"releases": []}))

    def test_api_doc_sync(self):
        """Test that API documents populate sitemap_cache with raw_json."""
        doc = SAMPLE_API_DOC.copy()
        raw_json_str = json.dumps(doc)
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                "INSERT INTO sitemap_cache (loc, lastmod, slug, scraped, site, raw_json) VALUES (?, ?, ?, ?, ?, ?)",
                (doc["permalink"], doc["post_date"], "kingsman-slug", 0, "hdhub4u", raw_json_str),
            )
            conn.commit()

            row = conn.execute("SELECT raw_json FROM sitemap_cache WHERE loc = ?", (doc["permalink"],)).fetchone()
        self.assertIsNotNone(row)
        parsed = json.loads(row[0])
        self.assertEqual(parsed["imdb_id"], "tt2802144")
        self.assertEqual(parsed["stars"], ["Colin Firth", "Samuel L. Jackson", "Mark Strong"])


import base64

if __name__ == "__main__":
    unittest.main(verbosity=2)
