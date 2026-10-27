#!/usr/bin/env python3
"""
Offline unit tests for stream_resolvers.py — no network, no catalog writes.

Run: python3 -S Fast_Fetch/importers/test_stream_resolvers.py
"""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import stream_resolvers as sr  # noqa: E402


class URLShapeTests(unittest.TestCase):
    def test_vidsrc_movie_tmdb_shape(self):
        entries = sr.resolver_urls(tmdb_id=27205, kind="movie")
        vidsrc = next(e for e in entries if e["resolver"] == "vidsrc")
        self.assertEqual(vidsrc["url"], "https://vidsrc.sh/embed/movie/27205")
        self.assertEqual(vidsrc["playback_type"], "embed")
        self.assertEqual(vidsrc["status"], "unknown")

    def test_vidsrc_episode_tmdb_shape(self):
        entries = sr.resolver_urls(tmdb_id=1396, kind="tv", season=1, episode=1)
        vidsrc = next(e for e in entries if e["resolver"] == "vidsrc")
        self.assertEqual(vidsrc["url"], "https://vidsrc.sh/embed/tv/1396/1/1")

    def test_vidsrc_imdb_fallback_shapes(self):
        movie = next(e for e in sr.resolver_urls(imdb_id="tt1375666", kind="movie")
                     if e["resolver"] == "vidsrc")
        episode = next(e for e in sr.resolver_urls(
            imdb_id="tt0903747", kind="tv", season=2, episode=3)
            if e["resolver"] == "vidsrc")
        self.assertEqual(movie["url"], "https://vidsrc.sh/embed/movie?imdb=tt1375666")
        self.assertEqual(
            episode["url"],
            "https://vidsrc.sh/embed/tv?imdb=tt0903747&season=2&episode=3")

    def test_superembed_movie_and_episode_shapes(self):
        movie = next(e for e in sr.resolver_urls(imdb_id="tt1375666", kind="movie")
                     if e["resolver"] == "superembed")
        episode = next(e for e in sr.resolver_urls(
            imdb_id="tt0903747", kind="tv", season=1, episode=1)
            if e["resolver"] == "superembed")
        self.assertEqual(movie["url"], "https://multiembed.mov/?video_id=tt1375666")
        self.assertEqual(
            episode["url"], "https://multiembed.mov/?video_id=tt0903747&s=1&e=1")

    def test_superembed_tmdb_shape_uses_the_flag(self):
        movie = next(e for e in sr.resolver_urls(tmdb_id=27205, kind="movie")
                     if e["resolver"] == "superembed")
        episode = next(e for e in sr.resolver_urls(
            tmdb_id=1396, kind="tv", season=2, episode=4)
            if e["resolver"] == "superembed")
        self.assertEqual(movie["url"], "https://multiembed.mov/?video_id=27205&tmdb=1")
        self.assertEqual(
            episode["url"],
            "https://multiembed.mov/?video_id=1396&tmdb=1&s=2&e=4")

    def test_vidlink_movie_and_episode_shapes(self):
        movie = next(e for e in sr.resolver_urls(tmdb_id=27205, kind="movie")
                     if e["resolver"] == "vidlink")
        episode = next(e for e in sr.resolver_urls(
            tmdb_id=1396, kind="tv", season=1, episode=1)
            if e["resolver"] == "vidlink")
        self.assertEqual(movie["url"], "https://vidlink.pro/movie/27205")
        self.assertEqual(episode["url"], "https://vidlink.pro/tv/1396/1/1")

    def test_vidlink_skipped_without_tmdb(self):
        names = [e["resolver"] for e in sr.resolver_urls(imdb_id="tt1375666", kind="movie")]
        self.assertNotIn("vidlink", names)

    def test_2embed_movie_and_episode_shapes(self):
        movie = next(e for e in sr.resolver_urls(tmdb_id=27205, kind="movie")
                     if e["resolver"] == "2embed")
        episode = next(e for e in sr.resolver_urls(
            tmdb_id=1396, kind="tv", season=1, episode=2)
            if e["resolver"] == "2embed")
        self.assertEqual(movie["url"], "https://www.2embed.cc/embed/27205")
        self.assertEqual(episode["url"], "https://www.2embed.cc/embedtv/1396&s=1&e=2")

    def test_2embed_imdb_fallback_shapes(self):
        movie = next(e for e in sr.resolver_urls(imdb_id="tt1375666", kind="movie")
                     if e["resolver"] == "2embed")
        episode = next(e for e in sr.resolver_urls(
            imdb_id="tt0903747", kind="tv", season=1, episode=1)
            if e["resolver"] == "2embed")
        self.assertEqual(movie["url"],
                         "https://www.2embed.cc/embed/imdb/movie?id=tt1375666")
        self.assertEqual(episode["url"],
                         "https://www.2embed.cc/embed/imdb/tv?id=tt0903747&s=1&e=1")

    def test_tmdb_preferred_when_both_ids_given(self):
        entries = sr.resolver_urls(27205, "tt1375666", "movie")
        vidsrc = next(e for e in entries if e["resolver"] == "vidsrc")
        self.assertIn("/embed/movie/27205", vidsrc["url"])

    def test_every_entry_has_the_contract_keys(self):
        entries = sr.resolver_urls(27205, "tt1375666", "tv", 1, 1)
        self.assertTrue(entries)
        for entry in entries:
            self.assertEqual(set(entry), {"resolver", "url", "playback_type", "status"})
            self.assertTrue(entry["url"].startswith("https://"))
            self.assertEqual(entry["playback_type"], "embed")
            self.assertEqual(entry["status"], "unknown")

    def test_one_entry_per_provider_in_stable_order(self):
        entries = sr.resolver_urls(27205, "tt1375666", "movie")
        names = [e["resolver"] for e in entries]
        self.assertEqual(names, ["vidsrc", "superembed", "vidlink", "2embed"])
        self.assertEqual(len(names), len(set(names)))

    def test_urls_point_at_each_provider_base(self):
        entries = sr.resolver_urls(27205, "tt1375666", "movie")
        for entry in entries:
            self.assertTrue(entry["url"].startswith(sr.PROVIDERS[entry["resolver"]]["base_url"]))


class IdentityHandlingTests(unittest.TestCase):
    def test_missing_ids_returns_empty(self):
        self.assertEqual(sr.resolver_urls(), [])
        self.assertEqual(sr.resolver_urls(None, None, "movie"), [])

    def test_unknown_tmdb_forms_are_rejected(self):
        for bad in ("abc", "0", "-5", "1.5", "", "1234567890", True):
            self.assertIsNone(sr.normalize_tmdb(bad), bad)

    def test_unknown_imdb_forms_are_rejected(self):
        for bad in ("tt123", "1375666", "tt137566", "tt1234567890", "", "nm0000138"):
            self.assertIsNone(sr.normalize_imdb(bad), bad)

    def test_valid_ids_normalise(self):
        self.assertEqual(sr.normalize_tmdb("0027205"), 27205)
        self.assertEqual(sr.normalize_tmdb(27205), 27205)
        self.assertEqual(sr.normalize_imdb("TT1375666"), "tt1375666")

    def test_tv_requires_season_and_episode(self):
        self.assertEqual(sr.resolver_urls(1396, kind="tv"), [])
        self.assertEqual(sr.resolver_urls(1396, kind="tv", season=1), [])
        self.assertEqual(sr.resolver_urls(1396, kind="tv", episode=1), [])
        self.assertEqual(sr.resolver_urls(1396, kind="tv", season=0, episode=1), [])
        self.assertEqual(sr.resolver_urls(1396, kind="tv", season=1, episode="x"), [])

    def test_unknown_kind_returns_empty(self):
        self.assertEqual(sr.resolver_urls(27205, kind="anime"), [])
        self.assertEqual(sr.resolver_urls(27205, kind=""), [])

    def test_movie_needs_no_season(self):
        self.assertTrue(sr.resolver_urls(27205, kind="movie"))

    def test_unknown_id_never_reaches_a_url(self):
        self.assertEqual(sr.resolver_urls("not-an-id", "not-an-imdb", "movie"), [])


class StatusClassificationTests(unittest.TestCase):
    def test_success_codes_are_active(self):
        self.assertEqual(sr.classify_status(200), "active")
        self.assertEqual(sr.classify_status(204), "active")

    def test_gone_codes_are_dead(self):
        self.assertEqual(sr.classify_status(404), "dead")
        self.assertEqual(sr.classify_status(410), "dead")

    def test_refusal_codes_are_blocked(self):
        for code in (401, 403, 429, 503):
            self.assertEqual(sr.classify_status(code), "blocked", code)

    def test_other_failures_are_error(self):
        for code in (0, 400, 500, 502, 302):
            self.assertEqual(sr.classify_status(code), "error", code)

    def test_challenge_page_is_blocked_despite_200(self):
        self.assertEqual(
            sr.classify_status(200, "<title>Just a moment...</title>"), "blocked")
        self.assertEqual(
            sr.classify_status(200, "Checking your browser before accessing"), "blocked")

    def test_plain_player_shell_is_active(self):
        self.assertEqual(
            sr.classify_status(200, "<html><body><div id=player></div></body></html>"),
            "active")


class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "resolvers.db"

    def tearDown(self):
        self.tmp.cleanup()

    def _entries(self):
        return sr.resolver_urls(27205, "tt1375666", "movie")

    def test_probe_false_makes_no_network_call_and_no_write(self):
        entries = self._entries()
        with mock.patch.object(sr, "_http_probe",
                               side_effect=AssertionError("network used")) as probe:
            out = sr.validate(entries, probe=False, db_path=self.db)
        probe.assert_not_called()
        self.assertEqual(len(out), 4)
        self.assertTrue(all(e["status"] == "unknown" for e in out))
        self.assertNotIn("http_code", out[0])
        self.assertFalse(self.db.exists())

    def test_probe_true_records_http_code_final_url_and_status(self):
        entries = self._entries()
        with mock.patch.object(sr, "_http_probe",
                               return_value=(200, "https://vidsrc.sh/embed/movie/27205", "")):
            out = sr.validate(entries, probe=True, db_path=self.db)
        self.assertTrue(all(e["status"] == "active" for e in out))
        self.assertTrue(all(e["http_code"] == 200 for e in out))
        self.assertTrue(all(e["probed_at"] > 0 for e in out))
        self.assertTrue(self.db.exists())

    def test_probe_mixes_statuses_per_entry(self):
        entries = self._entries()
        answers = iter([
            (200, "u1", ""),
            (404, "u2", ""),
            (403, "u3", ""),
            (500, "u4", ""),
        ])
        with mock.patch.object(sr, "_http_probe", side_effect=lambda *a, **k: next(answers)):
            out = sr.validate(entries, probe=True, db_path=self.db)
        self.assertEqual([e["status"] for e in out],
                         ["active", "dead", "blocked", "error"])

    def test_probe_rows_land_in_resolver_probes(self):
        entries = self._entries()
        with mock.patch.object(sr, "_http_probe", return_value=(200, "final", "")):
            sr.validate(entries, probe=True, db_path=self.db)
        conn = sqlite3.connect(self.db)
        try:
            rows = conn.execute(
                "SELECT resolver, kind, id, url, http_code, status, probed_at"
                " FROM resolver_probes ORDER BY resolver;").fetchall()
        finally:
            conn.close()
        self.assertEqual(len(rows), 4)
        self.assertEqual({r[1] for r in rows}, {"movie"})
        # A bare validate() derives the id from each URL; probe_work() stamps
        # the work-level id instead. Both forms are accepted.
        self.assertEqual({r[2] for r in rows}, {"tmdb:27205", "imdb:tt1375666"})
        self.assertTrue(all(r[4] == 200 and r[5] == "active" and r[6] > 0 for r in rows))

    def test_reprobing_upserts_instead_of_duplicating(self):
        entries = self._entries()
        with mock.patch.object(sr, "_http_probe", return_value=(200, "u", "")):
            sr.validate(entries, probe=True, db_path=self.db)
        with mock.patch.object(sr, "_http_probe", return_value=(410, "u", "")):
            sr.validate(entries, probe=True, db_path=self.db)
        conn = sqlite3.connect(self.db)
        try:
            count = conn.execute("SELECT COUNT(*) FROM resolver_probes;").fetchone()[0]
            statuses = {r[0] for r in conn.execute("SELECT status FROM resolver_probes;")}
        finally:
            conn.close()
        self.assertEqual(count, 4)
        self.assertEqual(statuses, {"dead"})

    def test_seed_resolvers_writes_four_capability_rows(self):
        count = sr.seed_resolvers(self.db)
        self.assertEqual(count, 4)
        conn = sqlite3.connect(self.db)
        try:
            rows = dict(conn.execute("SELECT name, kinds || '|' || id_types FROM resolvers;"))
        finally:
            conn.close()
        self.assertEqual(json.loads(rows["vidsrc"].split("|")[0]), ["movie", "tv"])
        self.assertIn("imdb", json.loads(rows["superembed"].split("|")[1]))
        self.assertEqual(json.loads(rows["vidlink"].split("|")[1]), ["tmdb"])

    def test_database_holds_only_capability_and_probe_tables(self):
        with mock.patch.object(sr, "_http_probe", return_value=(200, "u", "")):
            sr.validate(self._entries(), probe=True, db_path=self.db)
        conn = sqlite3.connect(self.db)
        try:
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table';")}
            resolver_cols = [r[1] for r in conn.execute("PRAGMA table_info(resolvers);")]
            probe_cols = [r[1] for r in conn.execute("PRAGMA table_info(resolver_probes);")]
        finally:
            conn.close()
        self.assertEqual(tables, {"resolvers", "resolver_probes"})
        self.assertEqual(resolver_cols, ["name", "base_url", "kinds", "id_types", "notes"])
        self.assertEqual(probe_cols,
                         ["resolver", "kind", "id", "url", "http_code", "status", "probed_at"])

    def test_probe_work_offline_builds_urls_without_network(self):
        with mock.patch.object(sr, "_http_probe",
                               side_effect=AssertionError("network used")):
            entries = sr.probe_work(1396, "tt0903747", "tv", 1, 1,
                                    db_path=self.db, probe=False)
        self.assertEqual(len(entries), 4)
        self.assertTrue(all(e["kind"] == "tv" for e in entries))
        self.assertTrue(all(e["id"] == "imdb:tt0903747" for e in entries))
        self.assertTrue(all(e["status"] == "unknown" for e in entries))
        self.assertFalse(self.db.exists())

    def test_probe_work_tmdb_only_labels_the_id(self):
        entries = sr.probe_work(27205, None, "movie", db_path=self.db, probe=False)
        self.assertTrue(all(e["id"] == "tmdb:27205" for e in entries))

    def test_probe_work_without_id_returns_empty(self):
        self.assertEqual(sr.probe_work(None, None, "movie", db_path=self.db), [])

    def test_probe_identity_derives_query_style_movie(self):
        entry = {"url": "https://multiembed.mov/?video_id=27205&tmdb=1"}
        self.assertEqual(sr._probe_identity(entry), ("movie", "tmdb:27205"))

    def test_probe_identity_derives_query_style_episode(self):
        entry = {"url": "https://multiembed.mov/?video_id=1396&tmdb=1&s=1&e=1"}
        self.assertEqual(sr._probe_identity(entry), ("tv", "tmdb:1396"))


class CoverageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "catalog.db"
        conn = sqlite3.connect(self.db)
        conn.executescript(
            """
            CREATE TABLE posts (
                id INTEGER PRIMARY KEY,
                title TEXT, clean_title TEXT, year INTEGER,
                imdb_id TEXT, tmdb_id INTEGER, is_18_plus INTEGER DEFAULT 0
            );
            INSERT INTO posts VALUES (1,'A','A',2020,'tt1375666',NULL,0);
            INSERT INTO posts VALUES (2,'A','A',2020,'tt1375666',NULL,0);
            INSERT INTO posts VALUES (3,'B','B',2021,NULL,27205,0);
            INSERT INTO posts VALUES (4,'C','C',2022,NULL,NULL,0);
            INSERT INTO posts VALUES (5,'D','D',2023,NULL,NULL,1);
            """
        )
        conn.commit()
        conn.close()

    def tearDown(self):
        self.tmp.cleanup()

    def test_coverage_counts_distinct_works_with_ids(self):
        stats = sr.coverage(self.db)
        self.assertEqual(stats["posts"], 4)          # adult row excluded
        self.assertEqual(stats["posts_with_id"], 3)
        self.assertEqual(stats["works"], 3)          # A deduped, B, C
        self.assertEqual(stats["works_with_id"], 2)  # A and B
        self.assertEqual(stats["coverage_pct"], 66.7)

    def test_coverage_does_not_modify_the_catalog(self):
        before = self.db.read_bytes()
        sr.coverage(self.db)
        self.assertEqual(before, self.db.read_bytes())

    def test_coverage_missing_catalog_is_reported(self):
        stats = sr.coverage(Path(self.tmp.name) / "nope.db")
        self.assertIn("error", stats)


class CatalogPathTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.patch_dir = mock.patch.object(sr, "DATA_DIR", self.dir)
        self.patch_dir.start()

    def tearDown(self):
        self.patch_dir.stop()
        self.tmp.cleanup()

    def test_env_var_names_the_live_merged_catalog(self):
        live = self.dir / "live.db"
        live.write_bytes(b"")
        with mock.patch.dict("os.environ", {"RADD_DB_PATH": str(live)}, clear=False):
            self.assertEqual(sr.merged_catalog_path(), live)

    def test_newest_merged_catalog_wins_over_fast_fetch(self):
        (self.dir / "fast_fetch.db").write_bytes(b"")
        old = self.dir / "merged_catalog_20261001.db"
        new = self.dir / "merged_catalog_20261025.db"
        old.write_bytes(b"")
        new.write_bytes(b"")
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(sr.merged_catalog_path(), new)

    def test_fallback_is_fast_fetch(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(sr.merged_catalog_path(), self.dir / "fast_fetch.db")


if __name__ == "__main__":
    unittest.main(verbosity=2)
