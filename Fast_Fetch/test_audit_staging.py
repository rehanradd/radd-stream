#!/usr/bin/env python3
"""Offline tests for audit_staging.py — temp databases only, no network, no live catalog.

The headline case is the read-only promise: the auditor is pointed at databases it must
never modify, so every test snapshots the directory's bytes and timestamps and fails if
anything moved, including the sidecar files SQLite creates when a handle is writable.
"""

import contextlib
import hashlib
import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import audit_staging  # noqa: E402  (path is set up above, by design)


MODERN_POSTS = (
    "CREATE TABLE posts (id INTEGER PRIMARY KEY, title TEXT, is_18_plus INTEGER, "
    "media_type TEXT, raw_meta TEXT)"
)
MODERN_SOURCES = (
    "CREATE TABLE sources (id INTEGER PRIMARY KEY, release_id INTEGER, "
    "playback_type TEXT, status TEXT)"
)


def make_modern_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute(MODERN_POSTS)
    conn.execute("CREATE TABLE releases (id INTEGER PRIMARY KEY, post_id INTEGER)")
    conn.execute(MODERN_SOURCES)
    conn.executemany(
        "INSERT INTO posts (title, is_18_plus, media_type, raw_meta) VALUES (?,?,?,?)",
        [
            ("Subbed Show", 0, "series", json.dumps({"subtitles": [{"language": "English"}], "streams": [1]})),
            ("Plain Film", 1, "movie", json.dumps({"streams": [1, 2]})),
            ("Broken Blob", 0, "movie", "not json at all"),
            ("Urdu Subs", 0, "series", json.dumps({"subtitles": {"language": "Urdu"}})),
        ],
    )
    conn.executemany("INSERT INTO releases (post_id) VALUES (?)", [(1,), (2,), (3,)])
    conn.executemany(
        "INSERT INTO sources (release_id, playback_type, status) VALUES (?,?,?)",
        [
            (1, "embed", "active"),
            (1, "subtitle", "active"),
            (2, "download", "dead"),
            (2, "subtitle", "unknown"),
            (3, "embed", "active"),
        ],
    )
    conn.commit()
    conn.close()


def make_legacy_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE posts (id INTEGER PRIMARY KEY, title TEXT, is_18_plus INTEGER)")
    conn.execute("CREATE TABLE releases (id INTEGER PRIMARY KEY, post_id INTEGER)")
    conn.execute("CREATE TABLE download_sources (id INTEGER PRIMARY KEY, release_id INTEGER)")
    conn.execute("CREATE TABLE post_sources (id INTEGER PRIMARY KEY, post_id INTEGER)")
    conn.execute("INSERT INTO posts (title, is_18_plus) VALUES ('Adult Title', 1)")
    conn.execute("INSERT INTO releases (post_id) VALUES (1)")
    conn.execute("INSERT INTO download_sources (release_id) VALUES (1)")
    conn.execute("INSERT INTO download_sources (release_id) VALUES (1)")
    conn.execute("INSERT INTO post_sources (post_id) VALUES (1)")
    conn.commit()
    conn.close()


def directory_state(directory: Path) -> dict:
    """Every file's size, mtime and content hash — the fingerprint of an untouched tree."""
    state = {}
    for entry in sorted(directory.rglob("*")):
        if not entry.is_file():
            continue
        stat = entry.stat()
        state[entry.name] = (
            stat.st_size,
            stat.st_mtime_ns,
            hashlib.sha256(entry.read_bytes()).hexdigest(),
        )
    return state


class AuditModernDatabase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="audit_staging_"))
        self.db = self.tmp / "example.db"
        make_modern_db(self.db)
        self.before = directory_state(self.tmp)
        self.report = audit_staging.audit_database(self.db)

    def tearDown(self):
        for path in self.tmp.rglob("*"):
            if path.is_file():
                os.unlink(path)
        os.rmdir(self.tmp)

    def test_counts_each_core_table(self):
        self.assertEqual({"posts": 4, "releases": 3, "sources": 5}, self.report["counts"])
        self.assertEqual(["posts", "releases", "sources"], self.report["tables"])

    def test_subtitle_rows_come_from_the_playback_type_column(self):
        self.assertEqual(2, self.report["subtitle_source_rows"])
        self.assertEqual({"embed": 2, "subtitle": 2, "download": 1}, self.report["playback_types"])

    def test_adult_flag_counts_flagged_posts_only(self):
        self.assertTrue(self.report["adult_column_present"])
        self.assertEqual(1, self.report["adult_posts"])

    def test_source_health_breakdown_by_status(self):
        self.assertEqual({"active": 3, "dead": 1, "unknown": 1}, self.report["source_health"])

    def test_media_types_are_the_distinct_values_of_their_own_column(self):
        self.assertEqual({"movie": 2, "series": 2}, self.report["media_types"])

    def test_raw_meta_census_is_a_labelled_sample_and_counts_subtitle_entries(self):
        census = self.report["raw_meta"]
        self.assertEqual(4, census["sampled"])
        self.assertEqual(3, census["parsed"])
        self.assertEqual(1, census["unparsed"])
        self.assertEqual({"streams": 2, "subtitles": 2}, census["keys"])
        self.assertEqual(2, census["posts_with_subtitles"])
        self.assertEqual({"English": 1, "Urdu": 1}, census["subtitle_types"])

    def test_a_clean_database_produces_no_warnings(self):
        self.assertEqual([], self.report["warnings"])

    def test_the_auditor_does_not_write_anything(self):
        self.assertEqual(self.before, directory_state(self.tmp))

    def test_the_audit_dir_held_nothing_but_the_files_it_reported_on(self):
        result = audit_staging.audit_directory(self.tmp)
        self.assertEqual(["example.db"], [item["database"] for item in result["audited"]])
        self.assertEqual(self.before, directory_state(self.tmp))


class ReadOnlyHandleIsThePoint(unittest.TestCase):
    """The tool's safety claim, tested directly against SQLite rather than assumed."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="audit_staging_ro_"))
        self.db = self.tmp / "site.db"
        make_modern_db(self.db)

    def tearDown(self):
        for path in self.tmp.rglob("*"):
            if path.is_file():
                os.unlink(path)
        os.rmdir(self.tmp)

    def test_a_mode_ro_connection_refuses_writes(self):
        conn = sqlite3.connect("file:%s?mode=ro" % self.db, uri=True)
        try:
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute("INSERT INTO releases (post_id) VALUES (99)")
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute("UPDATE posts SET title = 'changed'")
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute("DELETE FROM sources")
        finally:
            conn.close()
        self.assertEqual(3, conn_total(self.db, "releases"))

    def test_a_missing_database_is_reported_not_created(self):
        missing = self.tmp / "never_written.db"
        report = audit_staging.audit_database(missing)
        self.assertFalse(missing.exists())
        self.assertTrue(any("cannot stat" in w for w in report["warnings"]))
        self.assertEqual({"posts": 0, "releases": 0, "sources": 0}, report["counts"])


def conn_total(path: Path, table: str) -> int:
    conn = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    try:
        return conn.execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0]
    finally:
        conn.close()


class AuditLegacyAndDriftedDatabases(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="audit_staging_legacy_"))

    def tearDown(self):
        for path in self.tmp.rglob("*"):
            if path.is_file():
                os.unlink(path)
        os.rmdir(self.tmp)

    def test_legacy_link_tables_are_named_instead_of_reporting_a_bare_zero(self):
        db = self.tmp / "vegamovies.db"
        make_legacy_db(db)
        report = audit_staging.audit_database(db)
        self.assertEqual({"posts": 1, "releases": 1, "sources": 0}, report["counts"])
        self.assertEqual({"download_sources": 2, "post_sources": 1}, report["fallback_source_rows"])
        self.assertIsNone(report["subtitle_source_rows"])
        self.assertTrue(
            any("no sources table" in w and "download_sources=2" in w for w in report["warnings"])
        )

    def test_missing_status_and_missing_adult_flag_become_their_own_warnings(self):
        db = self.tmp / "thin.db"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE posts (id INTEGER PRIMARY KEY, title TEXT)")
        conn.execute("CREATE TABLE releases (id INTEGER PRIMARY KEY)")
        conn.execute("CREATE TABLE sources (id INTEGER PRIMARY KEY, playback_type TEXT)")
        conn.execute("INSERT INTO sources (playback_type) VALUES ('subtitle')")
        conn.commit()
        conn.close()
        report = audit_staging.audit_database(db)
        self.assertEqual(1, report["subtitle_source_rows"])
        self.assertIsNone(report["source_health"])
        self.assertIsNone(report["adult_posts"])
        self.assertFalse(report["adult_column_present"])
        self.assertTrue(any("no status column" in w for w in report["warnings"]))
        self.assertTrue(any("no is_18_plus" in w for w in report["warnings"]))

    def test_an_empty_core_table_is_called_out(self):
        db = self.tmp / "fresh.db"
        conn = sqlite3.connect(str(db))
        conn.execute(MODERN_POSTS)
        conn.execute("CREATE TABLE releases (id INTEGER PRIMARY KEY)")
        conn.execute(MODERN_SOURCES)
        conn.commit()
        conn.close()
        report = audit_staging.audit_database(db)
        self.assertTrue(any("posts is empty" in w for w in report["warnings"]))
        self.assertTrue(any("sources is empty" in w for w in report["warnings"]))


class DirectorySelectionAndOutput(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="audit_staging_dir_"))
        make_modern_db(self.tmp / "site.db")
        make_legacy_db(self.tmp / "other.db")
        for name in (
            "merged_catalog_20261025.db",
            "fast_fetch.db",
            "site_backup.db",
            "user_state.db",
            "resolvers.db",
            "notes.txt",
        ):
            (self.tmp / name).write_bytes(b"do not touch")
        self.before = directory_state(self.tmp)

    def tearDown(self):
        for path in self.tmp.rglob("*"):
            if path.is_file():
                os.unlink(path)
        os.rmdir(self.tmp)

    def test_skip_rules_keep_only_per_site_staging_catalogs(self):
        result = audit_staging.audit_directory(self.tmp)
        self.assertEqual(["other.db", "site.db"], [item["database"] for item in result["audited"]])
        self.assertEqual([], result["skipped"])

    def test_all_lists_the_skipped_files_with_a_reason(self):
        result = audit_staging.audit_directory(self.tmp, include_skipped=True)
        reasons = {item["database"]: item["reason"] for item in result["skipped"]}
        self.assertEqual(
            {
                "merged_catalog_20261025.db": "merged catalog",
                "fast_fetch.db": "not a staging catalog",
                "site_backup.db": "backup snapshot",
                "user_state.db": "not a staging catalog",
                "resolvers.db": "not a staging catalog",
            },
            reasons,
        )
        # The inventory glob is *.db, so a stray non-database file is never opened and
        # never claimed to be a staging catalog — it belongs to neither list.
        names = {item["database"] for item in result["audited"]} | set(reasons)
        self.assertNotIn("notes.txt", names)

    def test_totals_add_the_audited_catalogs_only(self):
        totals = audit_staging.audit_directory(self.tmp)["totals"]
        self.assertEqual(2, totals["databases"])
        self.assertEqual(5, totals["posts"])
        self.assertEqual(4, totals["releases"])
        self.assertEqual(5, totals["sources"])
        self.assertEqual(2, totals["subtitle_sources"])
        self.assertEqual(2, totals["adult_posts"])
        self.assertEqual(1, totals["databases_with_schema_warnings"])

    def test_json_output_is_machine_readable_and_agrees_with_the_report(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = audit_staging.main(["--data-dir", str(self.tmp), "--json"])
        self.assertEqual(0, code)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(2, payload["totals"]["databases"])
        self.assertEqual(["other.db", "site.db"], [d["database"] for d in payload["audited"]])

    def test_human_output_renders_every_audited_database(self):
        result = audit_staging.audit_directory(self.tmp)
        table = audit_staging.render_table(result)
        self.assertIn("site.db", table)
        self.assertIn("other.db", table)
        self.assertIn("TOTAL (2 catalogs)", table)
        self.assertIn("no sources table", table)

    def test_the_whole_directory_is_still_untouched_after_a_full_pass(self):
        with contextlib.redirect_stdout(io.StringIO()):
            audit_staging.main(["--data-dir", str(self.tmp)])
            audit_staging.main(["--data-dir", str(self.tmp), "--json", "--all"])
        self.assertEqual(self.before, directory_state(self.tmp))

    def test_a_missing_directory_warns_instead_of_crashing(self):
        result = audit_staging.audit_directory(self.tmp / "nowhere")
        self.assertEqual([], result["audited"])
        self.assertTrue(any("does not exist" in w for w in result["warnings"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
