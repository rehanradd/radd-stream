#!/usr/bin/env python3
"""
test_katmoviehd_import.py — Comprehensive unit tests for KatMovieHD staging importer.
Zero external dependencies. 100% Python standard library.
"""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import import_katmoviehd


class TestTitleCleaning(unittest.TestCase):
    def test_movie_with_year(self):
        raw = "The Campaign (2012) Hindi Dubbed (ORG) &amp; English [Dual Audio] BluRay 1080p 720p 480p HD [Full Movie]"
        clean, year, season, ckey = import_katmoviehd.clean_katmoviehd_title(raw)
        self.assertEqual(clean, "The Campaign")
        self.assertEqual(year, 2012)
        self.assertIsNone(season)
        self.assertEqual(ckey, "the-campaign_2012")

    def test_series_with_season(self):
        raw = "The Punisher (Season 2) Hindi Dubbed (DD 5.1) &amp; English [Dual Audio] | WEB-DL 1080p 720p 480p HD [2017–2019 Marvel Series] [Episode 04 Added]"
        clean, year, season, ckey = import_katmoviehd.clean_katmoviehd_title(raw)
        self.assertEqual(clean, "The Punisher")
        self.assertEqual(year, 2017)
        self.assertEqual(season, 2)
        self.assertEqual(ckey, "the-punisher_s2")

    def test_multi_audio_and_4k(self):
        raw = "Colony (2026) Hindi Dubbed (ORG) &amp; Korean [Dual Audio] BluRay 4K 2160p 1080p 720p 480p SDR [Full Movie]"
        clean, year, season, ckey = import_katmoviehd.clean_katmoviehd_title(raw)
        self.assertEqual(clean, "Colony")
        self.assertEqual(year, 2026)
        self.assertIsNone(season)
        self.assertEqual(ckey, "colony_2026")


class TestDevalueChunkParsing(unittest.TestCase):
    def test_valid_chunk_parsing(self):
        chunk_line = json.dumps({
            "type": "chunk",
            "id": 1,
            "data": [
                {"success": 1, "data": 2},
                True,
                {"items": 3, "page": 10, "perPage": 11, "totalItems": 12, "totalPages": 12},
                [4],
                {"categories": 5, "created": 7, "id": 8, "post_status": 9, "post_title": 10, "slug": 11, "thumbnail_image": 12},
                [6],
                "action",
                "2026-10-18T12:00:00Z",
                "12345",
                "publish",
                "Test Movie (2026)",
                "test-movie-2026",
                "https://image.tmdb.org/t/p/w500/test.jpg"
            ]
        })
        items = import_katmoviehd.parse_sveltekit_chunk(chunk_line)
        self.assertEqual(len(items), 1)
        it = items[0]
        self.assertEqual(it["slug"], "test-movie-2026")
        self.assertEqual(it["id"], "12345")
        self.assertEqual(it["post_title"], "Test Movie (2026)")
        self.assertEqual(it["categories"], ["action"])
        self.assertEqual(it["thumbnail_image"], "https://image.tmdb.org/t/p/w500/test.jpg")

    def test_empty_or_non_chunk(self):
        items = import_katmoviehd.parse_sveltekit_chunk('{"type":"data"}\n\n{"type":"skip"}')
        self.assertEqual(items, [])


class TestContentParsing(unittest.TestCase):
    def test_movie_releases_parsing(self):
        html_content = """
        <div>
          <a href="https://www.imdb.com/title/tt1790886/">IMDb Rating:-6.1/10</a>
          <h2>: DOWNLOAD LINKS :</h2>
          <a href="https://links.kmhd.me/file/The_4ea27398">480p Links [383MB]</a>
          <a href="https://links.kmhd.me/file/The_802fa3b8">720p Links [821MB]</a>
          <a href="https://links.kmhd.me/file/The_49a7402c">1080p 10bit Links [1.57GB]</a>
        </div>
        """
        releases = import_katmoviehd.parse_katmoviehd_releases(html_content)
        self.assertEqual(len(releases), 3)
        self.assertEqual(releases[0]["quality"], "480p")
        self.assertEqual(releases[0]["file_id"], "The_4ea27398")
        self.assertEqual(releases[1]["quality"], "720p")
        self.assertEqual(releases[1]["file_id"], "The_802fa3b8")
        self.assertEqual(releases[2]["quality"], "1080p")
        self.assertEqual(releases[2]["file_id"], "The_49a7402c")

    def test_series_episode_releases_parsing(self):
        html_content = """
        <div>
          <p class="p1"><b>Episode 1 - </b></p>
          <a href="https://links.kmhd.me/file/Marv_af24180c">1080p 10bit</a>
          <a href="https://links.kmhd.me/file/Marv_f0c22ba8">480p</a>
          <hr />
          <p class="p1"><b>Episode 2 - </b></p>
          <a href="https://links.kmhd.me/file/Marv_de55b0b9">1080p 10bit</a>
          <a href="https://links.kmhd.me/file/Marv_19f316fc">480p</a>
        </div>
        """
        releases = import_katmoviehd.parse_katmoviehd_releases(html_content, default_season=2)
        self.assertEqual(len(releases), 4)
        self.assertEqual(releases[0]["episode_number"], 1)
        self.assertEqual(releases[0]["season_number"], 2)
        self.assertEqual(releases[0]["file_id"], "Marv_af24180c")
        self.assertEqual(releases[2]["episode_number"], 2)
        self.assertEqual(releases[2]["season_number"], 2)
        self.assertEqual(releases[2]["file_id"], "Marv_de55b0b9")


class TestStagingDatabase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "katmoviehd.db"
        import_katmoviehd.init_staging_db(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_schema_created(self):
        with sqlite3.connect(str(self.db_path)) as conn:
            tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            self.assertIn("sitemap_cache", tables)
            self.assertIn("posts", tables)
            self.assertIn("releases", tables)
            self.assertIn("sources", tables)

    def test_save_and_retrieve_post(self):
        post_data = {
            "canonical_key": "the-campaign_2012",
            "title": "The Campaign",
            "original_title": "The Campaign (2012)",
            "year": 2012,
            "media_type": "movie",
            "imdb_id": "tt1790886",
            "poster_url": "https://image.tmdb.org/t/p/w500/test.jpg",
            "synopsis": None,
            "genres": json.dumps(["comedy"]),
            "rating": 6.1,
            "site": "katmoviehd",
            "post_url": "https://new.katmoviehd.top/the-campaign-2012-hindi",
            "releases": [
                {
                    "label": "720p Links [821MB]",
                    "quality": "720p",
                    "resolution": "720p",
                    "size_bytes": 861150158,
                    "season_number": None,
                    "episode_number": None,
                    "audio_languages": json.dumps(["Hindi", "English"]),
                    "codec": "x264",
                    "bridge_url": "https://links.kmhd.me/file/The_802fa3b8",
                    "sources": [
                        {
                            "source_name": "⚡ HubCloud [FSL Cloudflare R2]",
                            "service": "fsl_r2",
                            "resource_id": "le9qbqhol77qush",
                            "source_url": "https://hubcloud.ist/drive/le9qbqhol77qush",
                            "final_url": "https://r2.cloudflarestorage.com/test",
                            "is_temporary": 0,
                            "quality": "720p",
                        },
                        {
                            "source_name": "⚡ PixelDrain [Direct CDN]",
                            "service": "pixeldrain",
                            "resource_id": "negn6f",
                            "source_url": "https://pixeldrain.com/u/negn6f",
                            "final_url": "https://pixeldrain.com/api/file/negn6f",
                            "is_temporary": 0,
                            "quality": "720p",
                        },
                    ],
                }
            ],
        }

        ok = import_katmoviehd.save_post_to_staging_db(self.db_path, post_data)
        self.assertTrue(ok)

        with sqlite3.connect(str(self.db_path)) as conn:
            cur = conn.cursor()
            p_row = cur.execute("SELECT id, title, imdb_id, rating FROM posts WHERE canonical_key = 'the-campaign_2012'").fetchone()
            self.assertIsNotNone(p_row)
            self.assertEqual(p_row[1], "The Campaign")
            self.assertEqual(p_row[2], "tt1790886")
            self.assertEqual(p_row[3], 6.1)

            rel_row = cur.execute("SELECT id, label, quality, size_bytes FROM releases WHERE post_id = ?", (p_row[0],)).fetchone()
            self.assertIsNotNone(rel_row)
            self.assertEqual(rel_row[3], 861150158)

            src_rows = cur.execute("SELECT source_name, service, final_url FROM sources WHERE release_id = ?", (rel_row[0],)).fetchall()
            self.assertEqual(len(src_rows), 2)
            self.assertEqual(src_rows[0][1], "fsl_r2")
            self.assertEqual(src_rows[1][1], "pixeldrain")


LEGACY_CONTENT = """
<p>: DOWNLOAD LINKS ::</p>
<a href="magnet:?xt=urn:btih:E5913B225017BBB677335D7F3BCA71D74FA2CCC6&amp;dn=Lyod.2.2020.720p.HDRip.mkv">Magnet</a> |
<a href="https://ww.torrentshub.xyz/torrents/Rams.2020.720p.WEBRip.Hindi.Dub.mkv">Torrent</a>
<a href="https://new.gdtot.eu/file/2249188511">G-Drive- 1</a>
<a href="https://anonfiles.com/J3XaV4Uap5">Anon-File</a>
<a href="https://ninjastream.to/download/2KGZ9JB3Mm4Bn">Direct Link</a>
<a href="https://www.imdb.com/title/tt1234567/">IMDb</a>
<a href="https://en.wikipedia.org/wiki/Rams">Wiki</a>
<a href="https://1xcinema.com/movie/rams">Watch on 1XCinema</a>
<a href="https://lordhd.dad/post/rams">LordHD</a>
<a href="https://katmoviehd.fit/other">sister site</a>
"""


class LegacyLayoutTests(unittest.TestCase):
    """The pre-2022 download block (6,135 rows booked as failures on 2026-10-23)."""

    def test_legacy_block_yields_releases(self):
        rels = import_katmoviehd.parse_katmoviehd_legacy_releases(LEGACY_CONTENT)
        types = sorted(r["source_type"] for r in rels)
        self.assertEqual(types, ["anonfiles", "gdtot", "magnet", "ninjastream", "torrent"])
        self.assertTrue(all(r["bridge_url"] for r in rels))

    def test_legacy_block_ignores_nav_and_promo_links(self):
        urls = " ".join(r["bridge_url"] for r in
                        import_katmoviehd.parse_katmoviehd_legacy_releases(LEGACY_CONTENT))
        for host in ("imdb.com", "wikipedia", "1xcinema", "lordhd", "katmoviehd.fit"):
            self.assertNotIn(host, urls)

    def test_magnet_hash_and_quality_are_kept(self):
        rels = import_katmoviehd.parse_katmoviehd_legacy_releases(LEGACY_CONTENT)
        mag = next(r for r in rels if r["source_type"] == "magnet")
        self.assertEqual(mag["file_id"], "e5913b225017bbb677335d7f3bca71d74fa2ccc6")
        self.assertEqual(mag["quality"], "720p")

    def test_fallback_only_runs_when_modern_patterns_find_nothing(self):
        # Modern content keeps its own answer untouched.
        modern = import_katmoviehd.parse_katmoviehd_releases(
            '<a href="https://hubcloud.foo/drive/abc">1080p</a>')
        self.assertEqual([r["source_type"] for r in modern], ["hubcloud"])
        # Content with both layouts reports the modern links only.
        both = import_katmoviehd.parse_katmoviehd_releases(
            '<a href="https://hubcloud.foo/drive/abc">1080p</a>' + LEGACY_CONTENT)
        self.assertEqual([r["source_type"] for r in both], ["hubcloud"])

    def test_legacy_sources_are_stored_verbatim_without_api_lookup(self):
        calls = []

        class NoNetworkClient:
            def get_text(self, *a, **k):
                raise AssertionError("legacy links must not be resolved over HTTP")

            def get_api_json(self, url, timeout=12):
                calls.append(url)
                return None

        for r in import_katmoviehd.parse_katmoviehd_legacy_releases(LEGACY_CONTENT):
            size, sources = import_katmoviehd.resolve_file_sources(
                client=NoNetworkClient(), file_id=r["file_id"],
                bridge_url=r["bridge_url"], source_type=r["source_type"])
            self.assertEqual(size, None)
            self.assertEqual(len(sources), 1)
            self.assertEqual(sources[0]["service"], r["source_type"])
            self.assertEqual(sources[0]["final_url"], r["bridge_url"])
        self.assertEqual(calls, [], "the KatDrive REST API has no legacy records")


if __name__ == "__main__":
    unittest.main()
