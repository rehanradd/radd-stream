#!/usr/bin/env python3
"""Offline unit tests for merge_catalogs.py."""

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import fast_fetch
import merge_catalogs


class MergeCatalogsTests(unittest.TestCase):
    def test_merge_site_db_migrates_records_with_playback_type(self):
        with tempfile.TemporaryDirectory() as td:
            src_db = Path(td) / "source_multimovies.db"
            tgt_db = Path(td) / "unified_catalog.db"

            # Create source database
            fast_fetch.DB_PATH = src_db
            fast_fetch.init_db()
            post_id = fast_fetch.save_scraped_data(
                {
                    "url": "https://m1.multimovies.courses/movie/pushpa-2",
                    "slug": "pushpa-2",
                    "title": "Pushpa 2 (2024)",
                    "clean_title": "Pushpa 2",
                    "year": 2024,
                    "content_type": "movie",
                    "source_site": "multimovies",
                    "releases": [{
                        "release_title": "Pushpa 2 Cineverse",
                        "quality": "1080p",
                        "source_site": "multimovies",
                        "sources": [{
                            "source_name": "Cineverse [iframe]",
                            "service": "cineverse",
                            "resource_id": "pushpa2-cineverse",
                            "source_url": "https://embed.example/movie/pushpa2",
                            "final_url": "https://embed.example/movie/pushpa2",
                            "playback_type": "iframe",
                        }],
                    }],
                },
                enrich_metadata=False,
                ensure_db=False,
            )

            # Now merge into target DB
            stats = merge_catalogs.merge_site_db(src_db, tgt_db, verbose=False)
            self.assertEqual(stats["posts_merged"], 1)
            self.assertEqual(stats["releases_merged"], 1)
            self.assertEqual(stats["sources_merged"], 1)

            # Verify target DB has the record and playback_type
            fast_fetch.DB_PATH = tgt_db
            with fast_fetch.get_db() as conn:
                row = conn.execute(
                    """
                    SELECT p.clean_title, r.release_title, ds.playback_type, ds.source_url
                    FROM posts p
                    JOIN releases r ON r.post_id = p.id
                    JOIN download_sources ds ON ds.release_id = r.id
                    WHERE p.clean_title = 'Pushpa 2'
                    """
                ).fetchone()

                self.assertIsNotNone(row)
                self.assertEqual(row["clean_title"], "Pushpa 2")
                self.assertEqual(row["playback_type"], "iframe")
                self.assertEqual(row["source_url"], "https://embed.example/movie/pushpa2")


class StagingFamilyMergeTests(unittest.TestCase):
    """The hdhub4u-family staging schema (posts/releases/sources) must merge too."""

    def _make_staging_db(self, path: Path):
        import sqlite3
        conn = sqlite3.connect(path)
        conn.executescript(
            """
            CREATE TABLE posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                canonical_key TEXT, title TEXT, original_title TEXT, year INTEGER,
                media_type TEXT, imdb_id TEXT, tmdb_id TEXT, poster_url TEXT,
                backdrop_url TEXT, rating REAL, genres TEXT, synopsis TEXT,
                languages TEXT, is_18_plus INTEGER DEFAULT 0, site TEXT, post_url TEXT
            );
            CREATE TABLE releases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                post_id INTEGER, label TEXT, quality TEXT, resolution TEXT,
                size_bytes INTEGER, season_number INTEGER, episode_number INTEGER,
                codec TEXT, bridge_url TEXT, audio_languages TEXT
            );
            CREATE TABLE sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                release_id INTEGER, source_name TEXT, service TEXT, resource_id TEXT,
                source_url TEXT, final_url TEXT, is_temporary INTEGER, quality TEXT
            );
            """
        )
        cur = conn.execute(
            "INSERT INTO posts (canonical_key, title, original_title, year, media_type,"
            " poster_url, backdrop_url, rating, genres, synopsis, languages, is_18_plus, site,"
            " post_url) VALUES ('shivaay_2016', 'Shivaay', 'Shivaay (2016) Hindi', 2016,"
            " 'movie', 'https://cdn/p.jpg', 'https://cdn/b.jpg', 6.1, '[\"Action\"]',"
            " 'A man hunts for his daughter', '[\"Hindi\"]', 0, 'hdhub4u',"
            " 'https://new8.hdhub4u.cl/shivaay-2016.html')"
        )
        post_id = cur.lastrowid
        cur.execute(
            "INSERT INTO releases (post_id, label, quality, resolution, size_bytes,"
            " season_number, episode_number, codec, bridge_url, audio_languages)"
            " VALUES (?, 'Shivaay 1080p', '1080p', '1920x1080', 2408476672, NULL, NULL,"
            " 'x264', 'https://linkrit.example/?id=9', '[\"Hindi\"]')",
            (post_id,),
        )
        rel_id = cur.lastrowid
        conn.execute(
            "INSERT INTO sources (release_id, source_name, service, resource_id,"
            " source_url, final_url, is_temporary, quality) VALUES"
            " (?, 'HubCloud', 'hubcloud', '9', 'https://linkrit.example/?id=9',"
            " 'https://hubcloud.ist/drive/9', 0, '1080p')",
            (rel_id,),
        )
        conn.commit()
        conn.close()

    def test_staging_schema_merges_into_unified(self):
        with tempfile.TemporaryDirectory() as td:
            src_db = Path(td) / "hdhub4u.db"
            tgt_db = Path(td) / "unified.db"
            self._make_staging_db(src_db)

            stats = merge_catalogs.merge_site_db(src_db, tgt_db, verbose=False)
            self.assertEqual(stats["posts_merged"], 1)
            self.assertEqual(stats["releases_merged"], 1)
            self.assertEqual(stats["sources_merged"], 1)

            fast_fetch.DB_PATH = tgt_db
            with fast_fetch.get_db() as conn:
                post = conn.execute(
                    "SELECT clean_title, content_type, source_site, url, is_18_plus,"
                    " genres, synopsis, imdb_rating, poster_url FROM posts").fetchone()
                self.assertEqual(post["clean_title"], "Shivaay")
                self.assertEqual(post["source_site"], "hdhub4u")
                self.assertEqual(post["url"], "https://new8.hdhub4u.cl/shivaay-2016.html")
                self.assertEqual(post["is_18_plus"], 0)
                self.assertEqual(post["content_type"], "movie")
                self.assertAlmostEqual(float(post["imdb_rating"]), 6.1)
                self.assertIn("Action", post["genres"])

                rel = conn.execute(
                    "SELECT release_title, quality, codec, size, languages, intermediate_url"
                    " FROM releases").fetchone()
                self.assertEqual(rel["release_title"], "Shivaay 1080p")
                self.assertEqual(rel["size"], "2.24 GB")
                self.assertEqual(rel["intermediate_url"], "https://linkrit.example/?id=9")

                src = conn.execute(
                    "SELECT service, final_url, playback_type, status FROM download_sources").fetchone()
                self.assertEqual(src["final_url"], "https://hubcloud.ist/drive/9")
                self.assertEqual(src["status"], "active")


    def test_duplicate_canonical_keys_merge_into_one_record(self):
        """Two staging rows for the same title must not create sibling catalog records."""
        with tempfile.TemporaryDirectory() as td:
            src_db = Path(td) / "ssrmovies.db"
            tgt_db = Path(td) / "unified.db"
            self._make_staging_db(src_db)
            conn = sqlite3.connect(src_db)
            conn.execute(
                "INSERT INTO posts (canonical_key, title, year, media_type, site, post_url)"
                " VALUES ('shivaay_2016', 'Shivaay', 2016, 'movie', 'ssrmovies',"
                " 'https://other.example/shivaay-2016/')")
            new_pid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.execute(
                "INSERT INTO releases (post_id, label, quality, size_bytes, codec, bridge_url)"
                " VALUES (?, 'Shivaay 720p', '720p', 966367642, 'x264',"
                " 'https://vcloud.example/77')", (new_pid,))
            rel_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.execute(
                "INSERT INTO sources (release_id, source_name, service, resource_id,"
                " source_url, final_url, is_temporary, quality) VALUES"
                " (?, 'VCloud', 'vcloud', '77', 'https://vcloud.example/77',"
                " 'https://vcloud.example/77', 0, '720p')", (rel_id,))
            conn.commit()
            conn.close()

            stats = merge_catalogs.merge_site_db(src_db, tgt_db, verbose=False)
            self.assertEqual(stats["posts_merged"], 2)

            with sqlite3.connect(tgt_db) as conn:
                conn.row_factory = sqlite3.Row
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0], 1)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM releases").fetchone()[0], 2)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM download_sources").fetchone()[0], 2)
                # The displaced page URL is preserved as a post source.
                recorded = {r[0] for r in conn.execute(
                    "SELECT url FROM post_sources WHERE post_id = 1").fetchall()}
                self.assertIn("https://other.example/shivaay-2016/", recorded)


    def test_conflicting_post_is_recorded_and_merge_continues(self):
        """One impossible identity must not abandon the remaining thousand posts of a site."""
        with tempfile.TemporaryDirectory() as td:
            src_db = Path(td) / "hdtvb.db"
            tgt_db = Path(td) / "unified.db"
            self._make_staging_db(src_db)
            conn = sqlite3.connect(src_db)
            conn.execute(
                "UPDATE posts SET media_type = 'complete_season' WHERE id = 1")
            conn.execute(
                "UPDATE releases SET season_number = 4 WHERE post_id = 1")
            conn.execute(
                "INSERT INTO posts (canonical_key, title, year, media_type, site, post_url)"
                " VALUES ('other_2021', 'Other', 2021, 'movie', 'hdtvb',"
                " 'https://new8.hdhub4u.cl/other-2021.html')")
            other_pid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.execute(
                "INSERT INTO releases (post_id, label, quality, size_bytes, codec)"
                " VALUES (?, 'Other 720p', '720p', 1073741824, 'x264')", (other_pid,))
            conn.commit()
            conn.close()

            # First pass: the season page lands in the catalog as a series.
            merge_catalogs.merge_site_db(src_db, tgt_db, verbose=False)

            # Second pass: the same page now claims to be a movie — unmergeable,
            # but it must be logged rather than crash the run.
            conn = sqlite3.connect(src_db)
            conn.execute("UPDATE posts SET media_type = 'movie' WHERE id = 1")
            conn.execute("UPDATE releases SET season_number = NULL WHERE post_id = 1")
            conn.commit()
            conn.close()

            stats = merge_catalogs.merge_site_db(src_db, tgt_db, verbose=False)
            self.assertEqual(stats["posts_conflicted"], 1)
            self.assertEqual(stats["posts_merged"], 1)

            with sqlite3.connect(tgt_db) as db:
                db.row_factory = sqlite3.Row
                conflict = db.execute(
                    "SELECT url, error, source_db FROM merge_conflicts").fetchone()
                self.assertIsNotNone(conflict)
                self.assertIn("shivaay-2016", conflict["url"])
                self.assertIn("media type", conflict["error"])
                self.assertEqual(conflict["source_db"], str(src_db))
                # The clean post still merged alongside the conflict.
                titles = {r[0] for r in db.execute("SELECT clean_title FROM posts")}
                self.assertIn("Other", titles)


    def test_season_pack_and_episode_pack_pages_share_one_series(self):
        """The real 7starhd case: an 'S07 complete' page and an 'S07EP(01-06)' page
        are two prints of one season, and must not collapse into a movie or fight."""
        with tempfile.TemporaryDirectory() as td:
            src_db = Path(td) / "7starhd.db"
            tgt_db = Path(td) / "unified.db"
            self._make_staging_db(src_db)
            conn = sqlite3.connect(src_db)
            conn.execute(
                "UPDATE posts SET canonical_key='campus-beats_2026', title='Campus Beats',"
                " original_title='Campus Beats (2026) Hindi ORG S07 Complete Web Series',"
                " year=2026, media_type='series', site='7starhd',"
                " post_url='https://7starhd.rich/campus-beats-2026-s07-complete/' WHERE id = 1")
            conn.execute(
                "UPDATE releases SET season_number = 7, episode_number = NULL WHERE post_id = 1")
            conn.execute(
                "INSERT INTO posts (canonical_key, title, original_title, year, media_type,"
                " site, post_url) VALUES ('campus-beats_2026', 'Campus Beats',"
                " 'Campus Beats (2026) Hindi ORG S07EP(01-06) Web Series HDRip', 2026,"
                " 'movie', '7starhd', 'https://7starhd.rich/campus-beats-2026-s07ep01-06/')")
            ep_pid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.execute(
                "INSERT INTO releases (post_id, label, quality, size_bytes, codec,"
                " season_number, episode_number) VALUES (?, 'Campus Beats 1080p', '1080p',"
                " 3221225472, 'x264', 7, 3)", (ep_pid,))
            ep_rel = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.execute(
                "INSERT INTO sources (release_id, source_name, service, resource_id,"
                " source_url, final_url, is_temporary, quality) VALUES"
                " (?, 'BunnyDrive', 'bunny', '55', 'https://bunny.example/55',"
                " 'https://bunny.example/55/direct', 0, '1080p')", (ep_rel,))
            conn.commit()
            conn.close()

            stats = merge_catalogs.merge_site_db(src_db, tgt_db, verbose=False)
            self.assertEqual(stats["posts_conflicted"], 0)
            self.assertEqual(stats["posts_merged"], 2)

            with sqlite3.connect(tgt_db) as db:
                db.row_factory = sqlite3.Row
                posts = db.execute("SELECT id, content_type, url FROM posts").fetchall()
                self.assertEqual(len(posts), 1)
                self.assertEqual(posts[0]["content_type"], "series")
                self.assertEqual(
                    {r[0] for r in db.execute(
                        "SELECT url FROM post_sources WHERE post_id = ?", (posts[0]["id"],))},
                    {"https://7starhd.rich/campus-beats-2026-s07-complete/",
                     "https://7starhd.rich/campus-beats-2026-s07ep01-06/"},
                )
                rels = {r[0] for r in db.execute("SELECT release_title FROM releases")}
                self.assertEqual(rels, {"Shivaay 1080p", "Campus Beats 1080p"})


if __name__ == "__main__":
    unittest.main()
