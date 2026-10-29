#!/usr/bin/env python3
"""Offline tests for `migrate_search_indexes.py` — the reviewed index migration.

What had to be provable, in the order a reviewer would ask:

1. **It cannot surprise anyone.** `plan` writes nothing, `apply` without `--execute`
   writes nothing, the target path is never guessed, and the ledger's own schema is
   byte-for-byte unchanged afterwards: additive only, no recreate.
2. **It is idempotent.** A migration that fails on its second run gets re-run at 3 a.m.
   by someone reading this repo from a chat log.
3. **The FTS index is either in step with `posts` or the tool says so.** The triggers
   are the whole correctness argument for an external-content index, and this suite is
   what found that the two obvious consistency checks do not work here: `SELECT COUNT(*)
   FROM posts_fts` reads `posts` rather than the index, and FTS5's own `integrity-check`
   command reported no error on a database with a provably missing row. So `verify`
   counts the shadow table `posts_fts_docsize` and searches a token from sampled rows,
   and the tests require it to fail on a dropped trigger and on a damaged index.
4. **Nothing here can answer a user's question yet.** `media_search` does not read
   `posts_fts`, which is why a half-built index is an operational non-event. The last
   test pins that fact, because it is the reason this is safe to schedule at leisure.

    python3 -S Fast_Fetch/test_migrate_search_indexes.py
"""
import io
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.resolve()))

import catalog_v2                  # noqa: E402
import fast_fetch                  # noqa: E402
import migrate_search_indexes as mig  # noqa: E402


class MigrationFixture(unittest.TestCase):
    """A throwaway catalog in a temp directory, never the live one.

    The resolved path is printed because "development must not target the production
    state file" is a claim about a filename, and a claim about a filename belongs in
    the run output rather than in prose about the run.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "fixture_catalog.db"
        fast_fetch.init_db(self.db)
        self.conn = sqlite3.connect(self.db)
        self.conn.row_factory = sqlite3.Row
        self.addCleanup(self.conn.close)
        # The v2 schema is what step 1 indexes, so it has to exist here. It is created
        # and then committed immediately: DDL left open in a write transaction makes
        # every other writer on this box wait on a lock this fixture holds for the rest
        # of the run, which is the deadlock that stalled the sibling suite.
        catalog_v2.ensure_schema(self.conn)
        self.conn.commit()
        self.seed()
        self.conn.commit()
        print(f"\n[fixture] sqlite      : {sqlite3.sqlite_version}")
        print(f"[fixture] database    : {self.db}  ({self.db.stat().st_size} bytes)")
        print(f"[fixture] live catalog: {fast_fetch.DB_PATH} — untouched by this test")

    def seed(self, count=12):
        for i in range(count):
            self.conn.execute(
                "INSERT INTO posts (url, slug, title, clean_title, year, content_type)"
                " VALUES (?, ?, ?, ?, 2024, 'movie')",
                (f"https://seed.test/{i}", f"seed-{i}",
                 f"Seeded Movie {i} (2024)", f"Seeded Movie {i}"))
        self.conn.execute(
            "INSERT INTO cat_work_sites (work_id, source_site, post_id, page_url)"
            " VALUES (1, 'seed.test', 1, 'https://seed.test/0')")

    def cli(self, *argv):
        """Invoke the CLI the way the operator would, and keep what it printed.

        Named `cli` and not `run`: `TestCase.run` is unittest's own entry point, and
        shadowing it silently replaces the runner — setUp never fires and every test
        dies on a missing attribute instead on a real defect.
        """
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = mig.main(list(argv) + ["--target", str(self.db)])
        text = buffer.getvalue()
        print(text, end="")
        return code, text

    def schema_of(self, name="posts"):
        return self.conn.execute(
            "SELECT sql FROM sqlite_master WHERE name = ?", (name,)).fetchone()[0]

    def table_names(self):
        return {r[0] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','trigger','index')")}


class Safety(MigrationFixture):
    def test_target_must_be_a_file_and_is_never_guessed(self):
        with self.assertRaises(SystemExit) as raised:
            mig.open_target(str(self.db.parent / "does-not-exist.db"))
        self.assertIn("not a file", str(raised.exception))
        with self.assertRaises(SystemExit):
            with redirect_stdout(io.StringIO()):
                mig.main(["plan"])                      # no --target at all

    def test_plan_writes_nothing(self):
        before_bytes = self.db.read_bytes()
        before_names = self.table_names()
        code, text = self.cli("plan", "--with-fts")
        self.assertEqual(code, 0, text)
        self.assertEqual(self.db.read_bytes(), before_bytes, "plan modified the file")
        self.assertEqual(self.table_names(), before_names, "plan created schema")
        self.assertIn("STEP 1", text)
        self.assertIn("STEP 2", text)

    def test_apply_without_execute_writes_nothing(self):
        before_bytes = self.db.read_bytes()
        code, text = self.cli("apply", "--with-fts")
        self.assertEqual(code, 0, text)
        self.assertEqual(self.db.read_bytes(), before_bytes)
        self.assertIn("DRY RUN", text)

    def test_apply_is_additive_and_leaves_the_ledger_schema_alone(self):
        posts_sql_before = self.schema_of("posts")
        releases_sql_before = self.schema_of("releases")
        code, text = self.cli("apply", "--with-fts", "--execute")
        self.assertEqual(code, 0, text)
        self.assertEqual(self.schema_of("posts"), posts_sql_before,
                         "the migration altered the ledger table")
        self.assertEqual(self.schema_of("releases"), releases_sql_before)
        names = self.table_names()
        self.assertIn(mig.BRIDGE_INDEX, names)
        self.assertIn(mig.FTS_TABLE, names)
        for trigger in mig.TRIGGERS:
            self.assertIn(trigger, names, "no triggers means the index can lie")

    def test_apply_twice_is_not_an_error(self):
        first, first_text = self.cli("apply", "--with-fts", "--execute")
        second, second_text = self.cli("apply", "--with-fts", "--execute")
        self.assertEqual((first, second), (0, 0), second_text)
        self.assertIn("already present", second_text)

    def test_rollback_drops_only_what_step_two_added(self):
        self.cli("apply", "--with-fts", "--execute")
        code, text = self.cli("rollback", "--execute")
        self.assertEqual(code, 0, text)
        names = self.table_names()
        self.assertNotIn(mig.FTS_TABLE, names)
        for trigger in mig.TRIGGERS:
            self.assertNotIn(trigger, names)
        self.assertIn(mig.BRIDGE_INDEX, names,
                      "the read-side index is not part of the rollback")
        again, _ = self.cli("rollback", "--execute")
        self.assertEqual(again, 0, "rollback of an absent index must not fail")


class FtsStaysInStep(MigrationFixture):
    def test_the_built_index_finds_a_title_that_exists_and_not_one_that_does_not(self):
        code, text = self.cli("apply", "--with-fts", "--execute")
        self.assertEqual(code, 0, text)
        hit = self.conn.execute(
            "SELECT rowid FROM posts_fts WHERE posts_fts MATCH ?", ('"Seeded"',)).fetchall()
        self.assertGreater(len(hit), 0, "the rebuilt index cannot find its own content")
        miss = self.conn.execute(
            "SELECT rowid FROM posts_fts WHERE posts_fts MATCH ?", ('"NoSuchTitle"',)).fetchall()
        self.assertEqual(len(miss), 0)

    def test_insert_update_delete_keep_the_index_in_step(self):
        self.cli("apply", "--with-fts", "--execute")

        def find(token):
            return self.conn.execute(
                f"SELECT rowid FROM {mig.FTS_TABLE} WHERE {mig.FTS_TABLE} MATCH ?",
                (f'"{token}"',)).fetchall()

        self.conn.execute(
            "INSERT INTO posts (url, slug, title, clean_title, year, content_type)"
            " VALUES ('https://seed.test/new', 'new', 'Quarterly Report (2024)',"
            " 'Quarterly Report', 2024, 'movie')")
        self.assertEqual(len(find("Quarterly")), 1, "AFTER INSERT trigger is not firing")

        self.conn.execute("UPDATE posts SET clean_title = 'Twice Monthly',"
                          " title = 'Twice Monthly (2024)' WHERE slug = 'new'")
        self.assertEqual(len(find("Quarterly")), 0, "stale token still searchable")
        self.assertEqual(len(find("Monthly")), 1, "AFTER UPDATE trigger did not reindex")

        self.conn.execute("DELETE FROM posts WHERE slug = 'new'")
        self.assertEqual(len(find("Monthly")), 0, "AFTER DELETE trigger is not firing")
        self.conn.commit()

    def test_verify_reports_a_missing_trigger_that_a_row_count_would_not(self):
        """Inserting past a dropped trigger leaves `COUNT(*) FROM posts_fts` intact.

        Measured on this SQLite (3.45.1): the external-content table reads its content
        table, so the count said 21 while the index held 20, and
        `INSERT INTO posts_fts(posts_fts) VALUES('integrity-check')` reported no error
        on the mismatched database. The two signals that do see it are the shadow table
        `posts_fts_docsize` and a token from a sampled row, and `verify` must fail on
        both.
        """
        self.cli("apply", "--with-fts", "--execute")
        self.conn.execute(f"DROP TRIGGER {mig.TRIGGERS[0]}")
        self.conn.execute(
            "INSERT INTO posts (url, slug, title, clean_title, year, content_type)"
            " VALUES ('https://seed.test/orphan', 'orphan', 'Orphaned Record (2024)',"
            " 'Orphaned Record', 2024, 'movie')")
        self.conn.commit()
        posts = self.conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
        counted = self.conn.execute(f"SELECT COUNT(*) FROM {mig.FTS_TABLE}").fetchone()[0]
        docsize = self.conn.execute(
            f"SELECT COUNT(*) FROM {mig.FTS_TABLE}_docsize").fetchone()[0]
        self.assertEqual(posts, counted, "the read the reviewer would trust is the lie")
        self.assertEqual(docsize, posts - 1, "the shadow table must show the gap")
        code, text = self.cli("verify", "--with-fts")
        self.assertEqual(code, 1, text)
        self.assertIn("trigger", text)
        self.assertIn("index holds", text)

    def test_verify_catches_an_emptied_index_without_calling_it_a_pass(self):
        """Deleting the index outright damages the shadow tables, and every read of the
        FTS table then raises. `verify` must report that as a failure — an exception is
        never a green line — rather than printing a count and moving on.
        """
        self.cli("apply", "--with-fts", "--execute")
        self.conn.execute(f"DELETE FROM {mig.FTS_TABLE}")
        self.conn.commit()
        code, text = self.cli("verify", "--with-fts")
        self.assertEqual(code, 1, text)


class Scope(MigrationFixture):
    def test_step_one_alone_never_creates_the_fts_table(self):
        code, text = self.cli("apply", "--execute")
        self.assertEqual(code, 0, text)
        self.assertIn(mig.BRIDGE_INDEX, self.table_names())
        self.assertNotIn(mig.FTS_TABLE, self.table_names())
        self.assertEqual([t for t in mig.TRIGGERS if t in self.table_names()], [])

    def test_the_plan_prints_an_estimate_instead_of_a_promise(self):
        code, text = self.cli("plan", "--with-fts")
        self.assertEqual(code, 0, text)
        self.assertIn("estimate", text.lower())
        if mig.MEASURED_FTS_ROWS_PER_SECOND <= 0:
            self.assertIn("NOT MEASURED", text,
                          "an unmeasured build must not print a confident number")

    def test_media_search_cannot_read_this_index_yet(self):
        """The rollout-safety claim, pinned: no code path of the matcher names the
        table this migration builds, so a stale index cannot change an answer."""
        import media_search
        import inspect
        source = inspect.getsource(media_search)
        self.assertNotIn(mig.FTS_TABLE, source,
                         "media_search now reads posts_fts — retire this test and"
                         " re-review the rollout, the staleness argument is gone")
        for statement in mig._sqls(with_fts=True):
            self.assertNotIn("media_search", statement)

    def test_the_migration_is_stdlib_only(self):
        source = (Path(__file__).parent / "migrate_search_indexes.py").read_text()
        for line in source.splitlines():
            if line.startswith(("import ", "from ")):
                root = line.split()[1].split(".")[0]
                self.assertIn(root, ("argparse", "os", "re", "shutil", "sqlite3",
                                     "sys", "time", "pathlib", "__future__"),
                              f"non-stdlib import: {line}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
