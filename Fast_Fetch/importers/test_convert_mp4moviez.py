#!/usr/bin/env python3
"""Offline unit tests for convert_mp4moviez.py."""

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import fast_fetch
import merge_catalogs
from importers import convert_mp4moviez as cv


LEGACY_SCHEMA = """
CREATE TABLE sitemap_cache (
    url TEXT PRIMARY KEY,
    lastmod TEXT,
    processed INTEGER DEFAULT 0
);
CREATE TABLE posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_url TEXT UNIQUE,
    clean_title TEXT,
    year INTEGER,
    genres TEXT,
    duration TEXT,
    languages TEXT,
    cast_names TEXT,
    poster_url TEXT,
    synopsis TEXT,
    tags TEXT,
    is_18_plus INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE releases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id INTEGER,
    quality TEXT,
    url TEXT,
    resolved INTEGER DEFAULT 0
);
"""


def _make_legacy(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(LEGACY_SCHEMA)
    rows = [
        # (source_url, clean_title, year, is_18_plus, poster)
        ("https://www.mp4moviez.deal/marshals-(2026)-season-2-(episode-2)-"
         "hindi-dubbed-tv-series-hd-60944.html",
         "Download Marshals 2026 Season 2 Episode 2 Hindi Dubbed TV Series HDRip -",
         2026, 0, "https://cdn/p1.jpg"),
        ("https://www.mp4moviez.deal/marshals-(2026)-season-2-(episode-3)-"
         "hindi-dubbed-tv-series-hd-60945.html",
         "Download Marshals 2026 Season 2 Episode 3 Hindi Dubbed TV Series HDRip -",
         2026, 0, None),
        ("https://www.mp4moviez.deal/the-influencer-project-2026-hindi-"
         "(unofficial)-dubbed.html",
         "Download The Influencer Project 2026 Hindi Unofficial Dubbed in HD",
         2026, 1, None),
        ("https://www.mp4moviez.deal/the-influencer-project-(2026)-hindi-dubbed-"
         "hd-123.html",
         "Download The Influencer Project 2026 Hindi Dubbed HDRip -", 2026, 0, None),
        ("https://www.mp4moviez.deal/1917-(2019)-hindi-dubbed-movie-hd-45000.html",
         "Download 1917 2019 Hindi Dubbed Movie HDRip -", 2019, 0, None),
        ("https://www.mp4moviez.deal/1/bollywood-movies.html",
         "Download Bollywood Movies", 2026, 0, None),
        ("https://www.mp4moviez.locker/sitemap-movies-1.xml", "", 1999, 0, None),
    ]
    ids = {}
    for url, title, year, adult, poster in rows:
        cur = conn.execute(
            "INSERT INTO posts (source_url, clean_title, year, is_18_plus, poster_url,"
            " genres, languages) VALUES (?, ?, ?, ?, ?, 'Action', '[\"Hindi\"]')",
            (url, title, year, adult, poster))
        ids[url] = cur.lastrowid
    release_rows = [
        (ids["https://www.mp4moviez.deal/marshals-(2026)-season-2-(episode-2)-"
             "hindi-dubbed-tv-series-hd-60944.html"], "720p",
         "https://www.mp4moviez.deal/dl.php?id=60944&q=720&title=Marshals"),
        (ids["https://www.mp4moviez.deal/marshals-(2026)-season-2-(episode-2)-"
             "hindi-dubbed-tv-series-hd-60944.html"], "480p",
         "https://www.mp4moviez.deal/dl.php?id=60944&q=480&title=Marshals"),
        (ids["https://www.mp4moviez.deal/marshals-(2026)-season-2-(episode-3)-"
             "hindi-dubbed-tv-series-hd-60945.html"], "720p",
         "https://www.mp4moviez.deal/dl.php?id=60945&q=720&title=Marshals"),
        (ids["https://www.mp4moviez.deal/the-influencer-project-2026-hindi-"
             "(unofficial)-dubbed.html"], "1080p",
         "https://www.mp4moviez.deal/dl.php?id=70001&q=1080"),
        (ids["https://www.mp4moviez.deal/the-influencer-project-(2026)-hindi-dubbed-"
             "hd-123.html"], "720p",
         "https://www.mp4moviez.deal/dl.php?id=70002&q=720"),
        # Same quality + URL as the previous new-style page: must not duplicate.
        (ids["https://www.mp4moviez.deal/the-influencer-project-(2026)-hindi-dubbed-"
             "hd-123.html"], "720p",
         "https://www.mp4moviez.deal/dl.php?id=70002&q=720"),
        (ids["https://www.mp4moviez.deal/1917-(2019)-hindi-dubbed-movie-hd-45000.html"],
         "480p", "https://www.mp4moviez.deal/dl.php?id=45000&q=480"),
    ]
    conn.executemany(
        "INSERT INTO releases (post_id, quality, url) VALUES (?, ?, ?)", release_rows)
    conn.executemany(
        "INSERT INTO sitemap_cache (url, lastmod, processed) VALUES (?, ?, ?)",
        [("https://www.mp4moviez.deal/marshals-(2026)-season-2-(episode-2)-"
          "hindi-dubbed-tv-series-hd-60944.html", "2026-10-01", 1),
         ("https://www.mp4moviez.deal/1917-(2019)-hindi-dubbed-movie-hd-45000.html",
          "2026-10-02", 0)])
    conn.commit()
    conn.close()


def _make_other_staging(path: Path) -> None:
    """A different site claiming the same 1917 work under the same canonical key."""
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE posts (
            canonical_key TEXT PRIMARY KEY, title TEXT, clean_title TEXT, year INTEGER,
            media_type TEXT, poster_url TEXT, genres TEXT, languages TEXT,
            is_18_plus INTEGER DEFAULT 0, source_site TEXT, url TEXT
        );
        CREATE TABLE releases (
            id INTEGER PRIMARY KEY AUTOINCREMENT, post_canonical_key TEXT,
            label TEXT, quality TEXT, resolution TEXT, size_bytes INTEGER,
            codec TEXT, season_number INTEGER, episode_number INTEGER,
            bridge_url TEXT, audio_languages TEXT
        );
        CREATE TABLE sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT, release_id INTEGER,
            source_name TEXT, service TEXT, resource_id TEXT, source_url TEXT,
            final_url TEXT, status TEXT, playback_type TEXT, is_temporary INTEGER,
            quality TEXT
        );
        INSERT INTO posts VALUES ('1917_2019', '1917', '1917', 2019, 'movie',
            NULL, 'War', 'English', 0, 'pagalmovies',
            'https://www.pagalmovies.fit/movie/999/1917_(2019)_movie.html');
        INSERT INTO releases (post_canonical_key, label, quality, resolution)
            VALUES ('1917_2019', '1917 720p', '720p', '720p');
        INSERT INTO sources (release_id, source_name, service, source_url, status,
            playback_type, is_temporary, quality)
            VALUES (1, 'Pagal', 'pagalmovies',
            'https://www.pagalmovies.fit/file/999/1917.mkv.html', 'active',
            'url', 0, '720p');
        """
    )
    conn.commit()
    conn.close()


class ParseSlugTests(unittest.TestCase):
    def test_old_style_episode_slug(self):
        parsed = cv.parse_slug(
            "https://www.mp4moviez.deal/marshals-(2026)-season-2-(episode-2)-"
            "hindi-dubbed-tv-series-hd-60944.html", 2026)
        self.assertEqual(parsed["title"], "Marshals")
        self.assertEqual(parsed["year"], 2026)
        self.assertEqual(parsed["media_type"], "series")
        self.assertEqual((parsed["season"], parsed["episode"]), (2, 2))

    def test_new_style_movie_slug(self):
        parsed = cv.parse_slug(
            "https://www.mp4moviez.deal/c60932/the-influencer-project-2026-hindi-"
            "(unofficial)-dubbed.html", 2026)
        self.assertEqual(parsed["title"], "The Influencer Project")
        self.assertEqual(parsed["media_type"], "movie")

    def test_a_title_that_starts_with_a_year_keeps_the_recorded_year(self):
        parsed = cv.parse_slug(
            "https://www.mp4moviez.deal/1917-(2019)-hindi-dubbed-movie-hd-45000.html",
            2019)
        self.assertEqual(parsed["title"], "1917")
        self.assertEqual(parsed["year"], 2019)

    def test_misspelled_season_and_episode_ranges_are_still_series(self):
        parsed = cv.parse_slug(
            "https://www.mp4moviez.deal/c60806/marvels-the-punisher:-one-last-kill-"
            "(2026)-seaon-1-(episode-13)-hindi-dubbed-series.html", 2026)
        self.assertEqual(parsed["media_type"], "series")
        self.assertEqual((parsed["season"], parsed["episode"]), (1, 13))

    def test_a_year_at_the_end_of_the_slug_still_counts(self):
        parsed = cv.parse_slug(
            "https://www.mp4moviez.deal/c2024/rabb-da-radio-2-2019.html", 2019)
        self.assertEqual(parsed["title"], "Rabb Da Radio 2")
        self.assertEqual(parsed["year"], 2019)
        self.assertEqual(parsed["media_type"], "movie")

    def test_older_series_pages_without_a_year_are_still_works(self):
        parsed = cv.parse_slug(
            "https://www.mp4moviez.deal/c1093/game-of-thrones-season-8-episode-"
            "3-hindi-dubbed.html", 2026)
        self.assertEqual(parsed["title"], "Game Of Thrones")
        self.assertIsNone(parsed["year"])
        self.assertEqual(parsed["media_type"], "series")
        self.assertEqual((parsed["season"], parsed["episode"]), (8, 3))

    def test_shelves_sitemaps_and_static_pages_are_not_works(self):
        self.assertIsNone(cv.parse_slug(
            "https://www.mp4moviez.deal/1/bollywood-movies.html", 2026))
        self.assertIsNone(cv.parse_slug(
            "https://www.mp4moviez.deal/359/latest-hollywood-hindi-dubbed-movies-"
            "(2026).html", 2026))
        self.assertIsNone(cv.parse_slug(
            "https://www.mp4moviez.deal/c/dmca.htm", 2024))
        self.assertIsNone(cv.parse_slug(
            "https://www.mp4moviez.locker/sitemap-movies-1.xml", 1999))


class ConvertTests(unittest.TestCase):
    def test_vault_has_the_staging_shape_and_measured_values(self):
        with tempfile.TemporaryDirectory() as td:
            legacy = Path(td) / "mp4moviez.db"
            vault = Path(td) / "mp4moviez_staging.db"
            _make_legacy(legacy)
            stats = cv.convert(legacy, vault)
            self.assertEqual(stats["posts_written"], 3)
            self.assertEqual(stats["skipped_not_a_work"], 2)

            conn = sqlite3.connect(vault)
            conn.row_factory = sqlite3.Row
            try:
                tables = {r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")}
                self.assertTrue({"posts", "releases", "sources", "sitemap_cache"}
                                <= tables)
                post = conn.execute(
                    "SELECT * FROM posts WHERE canonical_key = 'marshals_2026'"
                ).fetchone()
                self.assertEqual(post["title"], "Marshals")
                self.assertEqual(post["media_type"], "series")
                self.assertEqual(post["source_site"], "mp4moviez")
                self.assertEqual(post["source_site"], cv.SITE)
                self.assertIn(post["url"], (
                    "https://www.mp4moviez.deal/marshals-(2026)-season-2-(episode-2)-"
                    "hindi-dubbed-tv-series-hd-60944.html",
                    "https://www.mp4moviez.deal/marshals-(2026)-season-2-(episode-3)-"
                    "hindi-dubbed-tv-series-hd-60945.html"))
                self.assertEqual(json.loads(post["seasons"]), [2])
                meta = json.loads(post["raw_meta"])
                self.assertEqual(len(meta["legacy_post_ids"]), 2)

                adult = conn.execute(
                    "SELECT is_18_plus FROM posts"
                    " WHERE canonical_key = 'the-influencer-project_2026'").fetchone()
                self.assertEqual(adult["is_18_plus"], 1)

                releases = conn.execute(
                    "SELECT * FROM releases WHERE post_canonical_key = 'marshals_2026'"
                    " ORDER BY id").fetchall()
                self.assertEqual(len(releases), 3)
                self.assertEqual({r["season_number"] for r in releases}, {2})
                self.assertEqual({r["episode_number"] for r in releases}, {2, 3})

                influencer = conn.execute(
                    "SELECT COUNT(*) FROM releases"
                    " WHERE post_canonical_key = 'the-influencer-project_2026'"
                ).fetchone()[0]
                self.assertEqual(influencer, 2)  # duplicated (720p,url) dropped

                sources = conn.execute("SELECT * FROM sources").fetchall()
                self.assertEqual(len(sources), releases.__len__() + influencer + 1)
                self.assertEqual({s["status"] for s in sources}, {"unverified"})
                self.assertEqual({s["playback_type"] for s in sources}, {"download"})
                self.assertTrue(all(s["source_name"] == "mp4moviez" for s in sources))
                self.assertIn("60944", {s["resource_id"] for s in sources})

                cache = conn.execute(
                    "SELECT loc, scraped FROM sitemap_cache ORDER BY loc").fetchall()
                self.assertEqual(len(cache), 2)
                self.assertEqual({r["scraped"] for r in cache}, {0, 1})
            finally:
                conn.close()

    def test_refuses_to_overwrite_the_legacy_source(self):
        with tempfile.TemporaryDirectory() as td:
            legacy = Path(td) / "mp4moviez.db"
            _make_legacy(legacy)
            with self.assertRaises(ValueError):
                cv.convert(legacy, legacy)

    def test_a_bounded_sample_merges_every_table_and_collapses_cross_site_keys(self):
        with tempfile.TemporaryDirectory() as td:
            legacy = Path(td) / "mp4moviez.db"
            vault = Path(td) / "mp4moviez_staging.db"
            other = Path(td) / "pagalmovies.db"
            target = Path(td) / "unified.db"
            _make_legacy(legacy)
            _make_other_staging(other)
            stats = cv.convert(legacy, vault)

            first = merge_catalogs.merge_site_db(vault, target, verbose=False)
            second = merge_catalogs.merge_site_db(other, target, verbose=False)
            self.assertEqual(first["posts_merged"], 3)
            self.assertEqual(second["posts_merged"], 1)

            fast_fetch.DB_PATH = target
            with fast_fetch.get_db() as conn:
                posts = conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
                self.assertEqual(posts, 3)  # 1917 did not become a sibling

                key_sources = conn.execute(
                    """
                    SELECT ps.source_site, ps.url FROM post_sources ps
                    JOIN posts p ON p.id = ps.post_id
                    WHERE p.canonical_key = '1917_2019' ORDER BY ps.source_site
                    """
                ).fetchall()
                self.assertEqual([r[0] for r in key_sources],
                                 ["mp4moviez", "pagalmovies"])

                releases = conn.execute(
                    "SELECT COUNT(*) FROM releases r JOIN posts p ON p.id = r.post_id"
                    " WHERE p.canonical_key = '1917_2019'").fetchone()[0]
                self.assertEqual(releases, 2)

                download_sources = conn.execute(
                    """
                    SELECT ds.service, ds.status FROM download_sources ds
                    JOIN releases r ON r.id = ds.release_id
                    JOIN posts p ON p.id = r.post_id
                    WHERE p.canonical_key = '1917_2019' ORDER BY ds.service
                    """
                ).fetchall()
                self.assertEqual([(r[0], r[1]) for r in download_sources],
                                 [("mp4moviez", "unverified"),
                                  ("pagalmovies", "active")])

                self.assertEqual(conn.execute(
                    "SELECT COUNT(*) FROM download_sources").fetchone()[0],
                    stats["sources_written"] + 1)


if __name__ == "__main__":
    unittest.main()
