#!/usr/bin/env python3
"""test_price_projection.py — the #18 sizing plan, pinned offline.

`price_projection.py` answers one question under a freeze that bars the obvious way to answer it:
*what does the projection rebuild cost, without executing it, without reading a row, and without a
production open?* So these tests are about the three ways that answer can be wrong.

**Conservation.** The four statements in `STATEMENTS` are quoted from `catalog_v2.py`, and the plan is
only a plan while the quotation is current. Each pinned string is asserted to be *literally present*
in the projection's source, so a refactor that changes the head pass or a per-post lookup breaks a
test instead of quietly pricing a query nobody issues. `CALIBRATION` gets the same treatment as the
census's tier table: the published RSS-per-retained-MB factor is recomputed from the published raw
numbers, with a tolerance, because `ru_maxrss` is a peak with 1 MB granularity.

**Classification.** Synthetic ledgers with the engine's own DDL: an indexed ledger must come back as
`SEARCH … USING INDEX`, an index-less twin as `SCAN`, and the verdict must change with it. A plan that
reports the wrong shape is worse than no plan, because it is what the next lane starts a rebuild on.

**The ruling, enforced.** Every SQL string that reaches the connection is recorded with
`set_trace_callback` and checked against `is_schema_only` — on a ledger that *does* hold 500 rows, so
"no content read" is demonstrated against a database that could have been read. Plus the `mode=ro`
guarantee at the connection level, a byte-identical check, and the sidecar check.

No production file, no network, no `config` import. Stdlib only.

    python3 -S Fast_Fetch/test_price_projection.py
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import price_projection as pp

#: `fast_fetch.init_db`'s Layer-0 DDL, copied rather than imported: `init_db` would also create the
#: engine's other tables and touch `config`, and this module's whole subject is four tables.
POSTS_DDL = """
CREATE TABLE posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT UNIQUE NOT NULL, slug TEXT, title TEXT,
    clean_title TEXT, year INTEGER, content_type TEXT, seasons TEXT, poster_url TEXT,
    backdrop_urls TEXT, imdb_rating TEXT, genres TEXT, synopsis TEXT, is_18_plus INTEGER DEFAULT 0,
    is_animated INTEGER DEFAULT 0, lastmod TEXT, created_at TIMESTAMP, updated_at TIMESTAMP,
    canonical_key TEXT)
"""
RELEASES_DDL = """
CREATE TABLE releases (
    id INTEGER PRIMARY KEY AUTOINCREMENT, post_id INTEGER NOT NULL, release_title TEXT,
    season TEXT, episode TEXT, quality TEXT, codec TEXT, size TEXT, languages TEXT,
    intermediate_url TEXT, source_site TEXT DEFAULT NULL, origin_url TEXT DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
"""
SOURCES_DDL = """
CREATE TABLE download_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT, release_id INTEGER NOT NULL, source_name TEXT,
    service TEXT, resource_id TEXT, source_url TEXT, final_url TEXT,
    playback_type TEXT DEFAULT 'url', is_temporary INTEGER DEFAULT 0, status TEXT DEFAULT 'active',
    is_resumable INTEGER DEFAULT 0, http_status INTEGER DEFAULT NULL,
    file_size_bytes INTEGER DEFAULT NULL, mime_type TEXT DEFAULT NULL,
    last_checked_at TIMESTAMP DEFAULT NULL, created_at TIMESTAMP, updated_at TIMESTAMP)
"""
POST_SOURCES_DDL = """
CREATE TABLE post_sources (
    post_id INTEGER NOT NULL, source_site TEXT NOT NULL, url TEXT NOT NULL, source_title TEXT,
    source_slug TEXT, first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (source_site, url))
"""
LAYER0_DDL = (POSTS_DDL, RELEASES_DDL, SOURCES_DDL, POST_SOURCES_DDL)

#: The engine's own index law for the three join columns (`fast_fetch.py:986`, `:1012`, `:1120`).
ENGINE_INDEXES = ("CREATE INDEX idx_releases_post ON releases(post_id)",
                  "CREATE INDEX idx_sources_rel ON download_sources(release_id)",
                  "CREATE INDEX idx_post_sources_post ON post_sources(post_id)")


def build_ledger(path, *, indexed: bool = True, rows: int = 0) -> Path:
    """A throwaway ledger shaped like the engine's, with or without the join indexes."""
    path = Path(path)
    conn = sqlite3.connect(str(path))
    conn.executescript(";\n".join(LAYER0_DDL) + ";")
    for i in range(rows):
        conn.execute("INSERT INTO posts (url, slug, title, clean_title, synopsis, canonical_key)"
                     " VALUES (?,?,?,?,?,?)",
                     ("https://s.example/%d" % i, "film-%d" % i, "Film %d" % i, "Film %d" % i,
                      "x" * 200, "k%d" % i))
        if i % 2 == 0:
            conn.execute("INSERT INTO releases (post_id, release_title, quality)"
                         " VALUES (?,?,?)", (i + 1, "Film %d 1080p" % i, "1080p"))
            conn.execute("INSERT INTO download_sources (release_id, source_name, source_url)"
                         " VALUES (?,?,?)", (i // 2 + 1, "host", "https://d.example/%d" % i))
        conn.execute("INSERT INTO post_sources (post_id, source_site, url) VALUES (?,?,?)",
                     (i + 1, "site_a", "https://s.example/%d" % i))
    if indexed:
        for ddl in ENGINE_INDEXES:
            conn.execute(ddl)
    conn.commit()
    conn.close()
    return path


def price_file(path, **kwargs) -> dict:
    """Open schema-only, price, close — so no test leaks a handle onto a ledger."""
    conn = pp.open_schema_only(path)
    try:
        return pp.price(conn, **kwargs)
    finally:
        conn.close()


def digest(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def plan_of(result: dict, label: str) -> dict:
    """The one priced statement named `label` — and a typo in a label is a failure, not a None."""
    return next(row for row in result["ledger_statements"] if row["label"] == label)


class StatementConservationTests(unittest.TestCase):
    """The plan is a quotation, and a quotation goes stale."""

    @classmethod
    def setUpClass(cls):
        cls.source = (Path(__file__).resolve().parent / "catalog_v2.py").read_text(encoding="utf-8")

    def test_every_priced_statement_is_still_in_the_projection_verbatim(self):
        stale = [row["label"] for row in pp.STATEMENTS if row["sql"] not in self.source]
        self.assertFalse(stale,
                         "%s is/are quoted from catalog_v2.py but not present in it — the projection"
                         " changed and this plan now prices queries nobody issues"
                         % ", ".join(stale))

    def test_the_priced_tables_are_exactly_the_four_layer0_tables(self):
        self.assertEqual(sorted({row["table"] for row in pp.STATEMENTS}), sorted(pp.LAYER0_TABLES),
                         "the projection's read set and the priced read set have diverged")
        import project_readonly
        self.assertEqual(sorted(pp.LAYER0_TABLES), sorted(project_readonly.LAYER0),
                         "the two tools that may open a ledger now disagree about what a ledger is")

    def test_the_nested_statement_multiplier_is_the_shape_of_the_loop(self):
        # 1 head pass, then two lookups per post (post_sources, releases) and one per release.
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        result = price_file(build_ledger(Path(tmp.name) / "ledger.db"), posts=100, releases=37)
        self.assertEqual(result["nested_statement_count"], 1 + 2 * 100 + 37)

    def test_the_calibration_is_the_arithmetic_of_the_published_numbers(self):
        cal = pp.CALIBRATION
        self.assertEqual(cal["payload_per_row_bytes"] * cal["synthetic_rows"], cal["payload_bytes"])
        measured_mb = cal["rss_delta_mb"] * 1e6 / cal["payload_bytes"]
        self.assertAlmostEqual(cal["rss_mb_per_retained_mb"], measured_mb, delta=0.05,
                               msg="the factor is 6 MB of peak RSS over 5.925 MB of retained text;"
                                   " peak RSS has 1 MB granularity, so the model is ±10%, and a"
                                   " factor that no longer follows from the raw numbers is a typo")

    def test_the_recorded_post_count_is_a_quotation_with_a_source(self):
        self.assertEqual(pp.RECORDED["posts"], 146_176)
        self.assertIn("146,176", self.source,
                      "RECORDED.posts is quoted from the stats-endpoint comment in catalog_v2.py; if"
                      " that comment no longer says it, this default is nobody's measurement")


class PlanClassificationTests(unittest.TestCase):
    """A plan that reports the wrong shape is worse than no plan."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def test_an_engine_shaped_ledger_walks_an_index_on_every_per_row_lookup(self):
        result = price_file(build_ledger(self.dir / "ledger.db", indexed=True, rows=40),
                            posts=40, releases=20)
        for row in result["ledger_statements"]:
            if row["per"] == "once":
                self.assertEqual(row["plan"], "SCAN",
                                 "the head pass reads every column of every post; no index makes"
                                 " SELECT p.* cheaper, and one full pass is the right shape")
                continue
            self.assertEqual(row["plan"], "SEARCH",
                             "%s planned %s: %s" % (row["label"], row["plan"], row["detail"]))
            self.assertTrue(row["covering_join"],
                            "%s found no index over %s" % (row["label"], row["join_column"]))
            self.assertTrue(row["matches_engine_ddl"])

    def test_the_per_row_lookups_plan_no_sort_because_id_is_the_rowid(self):
        """`ORDER BY id` is free, and the claim is measured rather than assumed.

        I wrote the opposite into this suite on the theory that a `post_id` index cannot produce an id
        order. The planner says otherwise on both shapes: a `WHERE post_id = ? ORDER BY id` walk emits
        (post_id, rowid) order, and a plain scan of a rowid table visits rows in rowid order. So there
        is no per-post sort in the rebuild — one fewer cost to price, and it is here so the next reader
        measures it instead of re-theorising it.
        """
        for indexed in (True, False):
            path = build_ledger(Path(self.tmp.name) / ("nosort-%s.db" % indexed),
                                indexed=indexed, rows=60)
            result = price_file(path)
            for row in result["ledger_statements"]:
                self.assertNotIn("TEMP B-TREE", row["detail"],
                                 "%s was expected to sort and the planner now says %s — either the"
                                 " projection changed its ORDER BY or this claim is wrong"
                                 % (row["label"], row["detail"]))

    def test_the_sort_flag_fires_when_a_lookup_really_does_sort(self):
        """The branch above needs a positive control, or "no sort" is just an unchecked string."""
        path = build_ledger(self.dir / "sorts.db", indexed=True, rows=20)
        conn = pp.open_schema_only(path)
        try:
            kind, detail = pp.plan(conn, "SELECT * FROM releases WHERE post_id = ?"
                                         " ORDER BY quality")
        finally:
            conn.close()
        self.assertEqual(kind, "SEARCH+sort")
        self.assertIn("USE TEMP B-TREE FOR ORDER BY", detail)

    def test_an_index_less_ledger_is_a_scan_on_the_hot_path_and_does_not_fit(self):
        result = price_file(build_ledger(self.dir / "bare.db", indexed=False, rows=40),
                            posts=40, releases=20)
        scans = sorted(row["label"] for row in result["ledger_statements"]
                       if row["per"] != "once" and row["plan"].startswith("SCAN"))
        self.assertEqual(scans, ["downloads per release", "releases per post", "sources per post"],
                         "with no index over the join column every outer row rescans the table")
        self.assertEqual(result["verdict"], "does not fit")
        self.assertTrue(any("full-table scans" in line for line in result["why"]))

    def test_a_hot_scan_refuses_the_rebuild_on_its_plan_alone(self):
        """`does not fit` here is a plan finding, not a memory finding.

        The cost model needs counts, and counts are a frozen content read, so the common typed-in
        invocation is `price_projection.py bare.db` with no numbers at all — and a ledger that scans
        `releases` once per outer row has to be refused by that invocation too. It was `indeterminate`
        until this case pinned it: the demotion only fired against a `fits` the cost model had
        produced, so the shape that guarantees a non-finishing rebuild reported that it did not know.
        """
        result = price_file(build_ledger(self.dir / "bare-noinputs.db", indexed=False, rows=20))
        self.assertIsNone(result["retention"], "no cost inputs were given, so there is no cost model")
        self.assertEqual(result["verdict"], "does not fit",
                         "the plan alone is enough to refuse this rebuild")
        self.assertTrue(any("full-table scans" in line for line in result["why"]))

    def test_index_drift_from_the_engine_ddl_is_reported_not_assumed_away(self):
        path = build_ledger(self.dir / "drift.db", indexed=False, rows=5)
        conn = sqlite3.connect(str(path))
        conn.execute("CREATE INDEX idx_releases_post ON releases(post_id)")
        conn.commit()
        conn.close()
        result = price_file(path, posts=5, releases=2)
        self.assertTrue(plan_of(result, "releases per post")["matches_engine_ddl"],
                        "the expected index name is what the engine's DDL would have created")
        self.assertFalse(plan_of(result, "downloads per release")["matches_engine_ddl"],
                         "download_sources lost idx_sources_rel and the plan must say so")
        self.assertTrue(any("index drift" in line for line in result["why"]),
                        "a ledger whose indexes differ from init_db's is a different ledger, and"
                        " silently calling it the same is how a plan lies")

    def test_a_layer0_table_without_the_join_column_is_reported_not_a_traceback(self):
        """Found on real vaults, not invented: `filmyhit.db`, `kisskh.db` and `moviesmela.db` carry a
        `releases` table with no `post_id` column, and `EXPLAIN QUERY PLAN` *parses* the statement —
        so pricing one of those ledgers raised `OperationalError: no such column: post_id` and the
        pass died instead of naming the drift. A ledger the projection cannot read is the finding.
        """
        path = self.dir / "no-post-id.db"
        conn = sqlite3.connect(str(path))
        conn.execute(POSTS_DDL)
        conn.execute("CREATE TABLE releases (id INTEGER PRIMARY KEY, release_title TEXT,"
                     " quality TEXT)")
        conn.execute(SOURCES_DDL)
        conn.execute(POST_SOURCES_DDL)
        conn.commit()
        conn.close()
        result = price_file(path)
        releases = plan_of(result, "releases per post")
        self.assertEqual(releases["plan"], "NO-COLUMN")
        self.assertIn("no post_id column in releases", releases["detail"])
        self.assertEqual(result["verdict"], "does not fit",
                         "the rebuild would raise here, not run slowly")
        self.assertTrue(any("cannot be planned" in line for line in result["why"]),
                        "the report has to name the lookup that cannot even be planned")
        self.assertEqual(plan_of(result, "sources per post")["plan"], "SCAN",
                         "post_sources does have post_id, so that half stays a scan and not a crash")

    def test_a_database_without_the_layer0_tables_is_refused(self):
        path = self.dir / "empty.db"
        conn = sqlite3.connect(str(path))
        conn.execute("CREATE TABLE other (id INTEGER)")
        conn.commit()
        conn.close()
        with self.assertRaises(pp.PricingRefused) as caught:
            price_file(path)
        self.assertIn("no layer-0 table", str(caught.exception).lower())


class CostModelTests(unittest.TestCase):
    """Row counts are inputs. A tool that guesses one is a tool that reads the ledger."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = build_ledger(Path(self.tmp.name) / "ledger.db", rows=20)

    def test_no_row_count_means_no_verdict_and_the_reason_says_why(self):
        result = price_file(self.path)
        self.assertEqual(result["verdict"], "indeterminate")
        self.assertIsNone(result["nested_statement_count"])
        self.assertTrue(any("content read" in line and "frozen" in line
                            for line in result["why"]),
                        "the refusal has to teach the next lane why the number is not free")

    def test_a_count_without_a_row_size_stays_indeterminate_instead_of_guessing(self):
        result = price_file(self.path, posts=146_176)
        self.assertEqual(result["verdict"], "indeterminate")
        self.assertEqual(result["retention"]["posts"], 146_176)
        self.assertIsNone(result["retention"]["estimated_retained_mb"])
        self.assertTrue(any("mean-row-bytes" in line for line in result["why"]))

    def test_the_retention_estimate_is_the_published_arithmetic(self):
        result = price_file(self.path, posts=1000, releases=500, mean_row_bytes=2000, free_mb=8000)
        expected = 1000 * 2000 * pp.CALIBRATION["rss_mb_per_retained_mb"] / 1e6
        self.assertAlmostEqual(result["retention"]["estimated_retained_mb"], round(expected, 1))
        self.assertEqual(result["verdict"], "fits")

    def test_the_same_ledger_does_not_fit_when_memory_is_gone(self):
        result = price_file(self.path, posts=146_176, releases=412_000,
                            mean_row_bytes=1975, free_mb=1500)
        self.assertEqual(result["verdict"], "does not fit")
        self.assertGreater(result["retention"]["estimated_retained_mb"], 0)
        self.assertTrue(any("staged" in line for line in result["why"]),
                        "the advice has to be the structural fix — stage the head pass — not"
                        " 'retry when the box is quieter'")

    def test_the_free_memory_floor_is_the_freeze_instruments_own_number(self):
        self.assertEqual(pp.MIN_FREE_MB, 1500,
                         "the rebuild is judged against the same floor the window instrument uses")
        result = price_file(self.path, posts=146_176, mean_row_bytes=1975, free_mb=100_000)
        self.assertEqual(result["verdict"], "fits")

    def test_plan_only_reports_the_shape_and_no_cost_model_at_all(self):
        result = price_file(self.path, posts=100, plan_only=True)
        self.assertIsNone(result["nested_statement_count"])
        self.assertIsNone(result["retention"])
        self.assertEqual(len(result["ledger_statements"]), len(pp.STATEMENTS))

    def test_mem_available_is_read_from_proc_not_from_the_database(self):
        free = pp.mem_available_mb()
        if free is not None:
            self.assertGreater(free, 0)
            self.assertLess(free, 1024 * 1024, "MB, not kB — a unit slip here doubles the verdict")


class SchemaOnlyProofTests(unittest.TestCase):
    """Muse's 09:07 ruling, checked against a ledger that does have rows in it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def test_every_statement_that_reaches_the_connection_is_schema_only(self):
        path = build_ledger(self.dir / "ledger.db", rows=500)
        before = digest(path)
        conn = pp.open_schema_only(path)
        recorded = pp.record_schema_only(conn)
        try:
            pp.price(conn, posts=500, releases=250, mean_row_bytes=1975, free_mb=8000)
        finally:
            conn.close()
        self.assertTrue(recorded, "a recorder installed after the work ran would prove nothing")
        self.assertEqual(pp.violations(recorded), [],
                         "a pricing pass that reads a content row is a production read wearing a"
                         " plan")
        self.assertEqual(digest(path), before, "the ledger is not this tool's to change")
        for suffix in ("-wal", "-shm", "-journal"):
            self.assertFalse(os.path.exists(str(path) + suffix),
                             "a read-only open cannot create %s, so one appearing means another"
                             " writer is in this file" % suffix)

    def test_the_grammar_refuses_the_statements_a_content_read_would_look_like(self):
        allowed = ["PRAGMA table_info(posts)",
                   "EXPLAIN QUERY PLAN SELECT * FROM releases WHERE post_id = ?",
                   "SELECT name FROM sqlite_master WHERE type='table'",
                   "SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name=?"]
        refused = ["SELECT COUNT(*) FROM posts",
                   "SELECT * FROM releases WHERE post_id = 7",
                   "UPDATE posts SET is_18_plus = 0",
                   "SELECT title FROM posts JOIN sqlite_master ON 1=1",
                   "DELETE FROM download_sources"]
        for sql in allowed:
            self.assertTrue(pp.is_schema_only(sql), "%s is schema-only by the ruling" % sql)
        for sql in refused:
            self.assertFalse(pp.is_schema_only(sql), "%s reads or writes rows" % sql)

    def test_the_connection_itself_refuses_an_update(self):
        conn = pp.open_schema_only(build_ledger(self.dir / "ledger.db", rows=10))
        try:
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute("UPDATE posts SET is_18_plus = 0")
        finally:
            conn.close()

    def test_production_and_snapshot_names_are_never_pricing_targets(self):
        for name in ("merged_catalog_20261025.db", "preapply_20261029_1726.db",
                     "fast_fetch.db", "user_state.db", "resolvers.db"):
            path = build_ledger(self.dir / name, rows=1)
            with self.assertRaises(pp.PricingRefused, msg="%s is not a pricing target" % name):
                pp.open_schema_only(path)


class CommandLineTests(unittest.TestCase):
    """The tool is typed by a person in a window, so its refusals have to be exit codes."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = build_ledger(Path(self.tmp.name) / "ledger.db", rows=30)

    def run_cli(self, *args, target=None):
        out = io.StringIO()
        argv = [str(self.path if target is None else target)] + list(args)
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = pp.main(argv)
        return code, out.getvalue()

    def test_an_indeterminate_verdict_is_a_nonzero_exit(self):
        code, text = self.run_cli()
        self.assertEqual(code, 4, "no counts typed in is not a plan; it must not exit 0")
        self.assertIn("indeterminate", text)

    def test_a_full_set_of_inputs_exits_zero_and_prints_the_proof(self):
        code, text = self.run_cli("--posts", "146176", "--releases", "412000",
                                  "--mean-row-bytes", "1975", "--free-mb", "1500")
        self.assertEqual(code, 0)
        self.assertIn("statements sent to the ledger, every one schema-only", text)

    def test_the_recorded_default_is_announced_as_a_quotation(self):
        code, text = self.run_cli("--default-posts")
        self.assertEqual(code, 4)
        self.assertIn("a quotation and not a measurement", text)

    def test_a_missing_path_is_a_usage_error_not_a_traceback(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = pp.main([])
        self.assertEqual(code, 2)

    def test_a_forbidden_ledger_is_refused_with_exit_3(self):
        code, text = self.run_cli(target=self.tmp.name + "/merged_catalog_20261025.db")
        self.assertEqual(code, 3)
        self.assertIn("refused", text)


def _workflow_escape(text: str) -> str:
    """:`::error::` message escaping — the runner reads these three sequences and nothing else."""
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _failure_digest(result) -> str:
    """Up to three lines per failing test, with the versions that made those lines true.

    This exists because the hosted log is not readable from this box: `/actions/runs/{id}/logs`
    answers 401 for the token-less lanes while `/check-runs/{id}/annotations` answers 200 to anyone.
    A `::error::` printed by the step's own process becomes one of those annotations, so a red run
    here can say *which* assertion broke instead of only saying that exit 1 happened. The tail is
    three lines rather than one because `assertEqual` puts the value it *got* above the value it
    wanted, and the wanted value alone is not a diagnosis. Versions ride along because a
    planner-wording claim is only true of a SQLite version.
    """
    heads = []
    for kind, group in (("FAIL", result.failures), ("ERROR", result.errors)):
        for test, trace in group:
            lines = [line.strip() for line in (trace or "").rstrip().splitlines() if line.strip()]
            heads.append("%s %s :: %s" % (kind, test.id(), " ⏐ ".join(lines[-3:])))
    return ("test_price_projection RED — ran %d, %d failures, %d errors | sqlite %s | python %s | %s"
            % (result.testsRun, len(result.failures), len(result.errors),
               sqlite3.sqlite_version, sys.version.split()[0], " || ".join(heads)))


if __name__ == "__main__":
    print("fixture: %s (offline, temp ledgers only — no production file, no network)"
          % Path(__file__).name)
    _suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules["__main__"])
    _result = unittest.TextTestRunner(verbosity=2).run(_suite)
    if not _result.wasSuccessful():
        # One annotation, truncated: the runner caps a check run at ten and drops the rest silently.
        print("::error::%s" % _workflow_escape(_failure_digest(_result))[:2500])
    sys.exit(0 if _result.wasSuccessful() else 1)
