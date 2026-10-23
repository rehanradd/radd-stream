#!/usr/bin/env python3
"""
test_desicinemas.py — Offline Unit Tests for DesiCinemas Importer & HLS Resolver
"""

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from import_desicinemas import (
    clean_desicinemas_title,
    init_staging_db,
    is_adult_content,
    parse_desicinemas_content,
    save_post_to_staging,
    unpack_dean_edwards,
)


class TestDesiCinemasImporter(unittest.TestCase):
    def test_clean_desicinemas_title_movie(self):
        raw = "Auron Mein Kahan Dum Tha (HD)"
        title, year, s_num, e_num, q, langs, mtype, key = clean_desicinemas_title(
            raw, "https://www.desicinemas.pk/movies/auron-mein-kahan-dum-tha/"
        )
        self.assertEqual(title, "Auron Mein Kahan Dum Tha")
        self.assertEqual(q, "HD")
        self.assertIsNone(s_num)
        self.assertIsNone(e_num)
        self.assertEqual(mtype, "movie")
        self.assertEqual(key, "auron-mein-kahan-dum-tha")

    def test_clean_desicinemas_title_with_year_and_lang(self):
        raw = "Pind Aala School (Punjabi) (HD) 2024"
        title, year, s_num, e_num, q, langs, mtype, key = clean_desicinemas_title(
            raw, "https://www.desicinemas.pk/movies/pind-aala-school/"
        )
        self.assertEqual(title, "Pind Aala School")
        self.assertEqual(year, 2024)
        self.assertEqual(langs, "Punjabi")
        self.assertEqual(q, "HD")
        self.assertEqual(mtype, "movie")
        self.assertEqual(key, "pind-aala-school-2024")

    def test_clean_desicinemas_title_episode(self):
        raw = "24 India Season 2 Episode 10"
        title, year, s_num, e_num, q, langs, mtype, key = clean_desicinemas_title(
            raw, "https://www.desicinemas.pk/episode/24-india-season-2-episode-10/"
        )
        self.assertEqual(title, "24 India")
        self.assertEqual(s_num, 2)
        self.assertEqual(e_num, 10)
        self.assertEqual(mtype, "episode")
        self.assertEqual(key, "24-india-s02e10")

    def test_adult_filter(self):
        self.assertTrue(is_adult_content("Hotshots 18+ Sensual Web Series"))
        self.assertTrue(is_adult_content("Ullu Erotic Video"))
        self.assertTrue(is_adult_content("Kooku Uncensored Romance"))
        self.assertFalse(is_adult_content("Auron Mein Kahan Dum Tha (HD)"))
        self.assertFalse(is_adult_content("Pind Aala School (Punjabi)"))

    def test_unpack_dean_edwards(self):
        # Realistic packed string from peytonepre.com
        sample_packed = """
        eval(function(p,a,c,k,e,d){while(c--)if(k[c])p=p.replace(new RegExp('\\\\b'+c.toString(a)+'\\\\b','g'),k[c]);return p}('4 0="3://1.2/5/6.7";',8,8,'stream_url|example|com|https|var|hls|master|m3u8'.split('|')))
        """
        unpacked = unpack_dean_edwards(sample_packed)
        self.assertIn("https://example.com/hls/master.m3u8", unpacked)

    def test_parse_desicinemas_content(self):
        sample_html = """
        <header><h1 class="Title">Auron Mein Kahan Dum Tha (HD)</h1></header>
        <div class="Description"><p>Two lovers are separated by fate.</p></div>
        <p class="Director"><span>Director:</span> <tt class="tt-at"><a href="https://example.com/dir">Neeraj Pandey</a></tt></p>
        <p class="Cast"><span>Cast:</span> <a href="https://example.com/c1">Ajay Devgn</a>, <a href="https://example.com/c2">Tabu</a></p>
        <p class="Genre"><span>Genre:</span> <a href="https://example.com/g1">Drama</a>, <a href="https://example.com/g2">Romance</a></p>
        <img data-src="//image.tmdb.org/t/p/original/jlnnwItfF1DsItXvAFJGRF6d985.jpg" />
        <img data-src="//image.tmdb.org/t/p/w1280/backdrop123.jpg" />
        <a href="https://www.imdb.com/title/tt1234567/">IMDb</a>
        <iframe src="https://www.desicinemas.pk/?trembed=0&#038;trid=1387&trtype=1"></iframe>
        """
        imdb_id, tmdb_id, poster, backdrop, synopsis, director, cast_names, genres, trembed_urls, direct_iframes = parse_desicinemas_content(
            sample_html, "https://www.desicinemas.pk/movies/auron-mein-kahan-dum-tha/"
        )
        self.assertEqual(imdb_id, "tt1234567")
        self.assertIn("jlnnwItfF1DsItXvAFJGRF6d985.jpg", poster)
        self.assertIn("backdrop123.jpg", backdrop)
        self.assertEqual(synopsis, "Two lovers are separated by fate.")
        self.assertEqual(director, "Neeraj Pandey")
        self.assertIn("Ajay Devgn", cast_names)
        self.assertIn("Drama", genres)
        self.assertEqual(len(trembed_urls), 1)
        self.assertIn("trembed=0", trembed_urls[0])
        self.assertEqual(len(direct_iframes), 0)

    def test_db_init_and_save(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
            db_path = Path(tf.name)

        try:
            init_staging_db(db_path)

            with sqlite3.connect(str(db_path)) as conn:
                conn.execute(
                    "INSERT INTO sitemap_cache (loc, slug, scraped) VALUES (?, ?, 0);",
                    ("https://www.desicinemas.pk/movies/test-film/", "test-film"),
                )

            res = {
                "loc": "https://www.desicinemas.pk/movies/test-film/",
                "success": True,
                "post": {
                    "canonical_key": "test-film-2024",
                    "title": "Test Film (HD)",
                    "clean_title": "Test Film",
                    "year": 2024,
                    "media_type": "movie",
                    "imdb_id": "tt9876543",
                    "tmdb_id": "1083590",
                    "poster_url": "https://image.tmdb.org/t/p/original/poster.jpg",
                    "backdrop_url": "https://image.tmdb.org/t/p/w1280/backdrop.jpg",
                    "synopsis": "A test synopsis.",
                },
                "releases": [
                    {
                        "label": "Test Film [HD]",
                        "quality": "HD",
                        "resolution": "720p",
                        "size_bytes": None,
                        "codec": None,
                        "season_number": None,
                        "episode_number": None,
                        "audio_languages": "Hindi",
                        "bridge_url": "https://www.desicinemas.pk/?trembed=0&trid=99&trtype=1",
                        "sources": [
                            {
                                "source_name": "⚡ Peytonepre Direct HLS Stream",
                                "service": "peytonepre_hls",
                                "resource_id": "sample123",
                                "source_url": "https://peytonepre.com/embed/sample123",
                                "final_url": "https://cdn.example.com/stream/master.m3u8",
                                "is_temporary": 1,
                            }
                        ],
                    }
                ],
            }

            save_post_to_staging(db_path, res)

            with sqlite3.connect(str(db_path)) as conn:
                p_row = conn.execute("SELECT clean_title, year, imdb_id, media_type FROM posts WHERE canonical_key = 'test-film-2024';").fetchone()
                self.assertIsNotNone(p_row)
                self.assertEqual(p_row[0], "Test Film")
                self.assertEqual(p_row[1], 2024)
                self.assertEqual(p_row[2], "tt9876543")
                self.assertEqual(p_row[3], "movie")

                rel_row = conn.execute("SELECT quality, bridge_url FROM releases WHERE post_canonical_key = 'test-film-2024';").fetchone()
                self.assertIsNotNone(rel_row)
                self.assertEqual(rel_row[0], "HD")

                src_row = conn.execute("SELECT source_name, service, final_url FROM sources;").fetchone()
                self.assertIsNotNone(src_row)
                self.assertIn("Direct HLS Stream", src_row[0])
                self.assertEqual(src_row[1], "peytonepre_hls")
                self.assertIn("master.m3u8", src_row[2])

                cache_row = conn.execute("SELECT scraped FROM sitemap_cache WHERE loc = 'https://www.desicinemas.pk/movies/test-film/';").fetchone()
                self.assertEqual(cache_row[0], 1)
        finally:
            if os.path.exists(str(db_path)):
                os.remove(str(db_path))


if __name__ == "__main__":
    unittest.main()
