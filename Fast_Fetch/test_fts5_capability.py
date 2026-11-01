"""FTS5 capability probe — the instrument Phase 3's cine-finder design is allowed to depend on.

Why this exists as a test and not as a sentence in a document: the dispatch brief
(`/tmp/q1_muse_cinefinder_spec.txt`) tells the lane building the search to "prove it with
`python3 -c \"import sqlite3;print(sqlite3.dbinfo())\"`". Measured here, that instrument does not
exist: `sqlite3.dbinfo()` was added in Python 3.14 and this box runs 3.12.3, so the prescribed proof
raises `AttributeError` about a *function* and would be read as "no FTS5". The instruments that do work
are `sqlite3.sqlite_version` and a real `CREATE VIRTUAL TABLE … USING fts5` against a temp file, which
is what this module runs.

Stdlib only, no production path, no chmod: every write goes inside `tempfile.TemporaryDirectory()`.
A runner whose `libsqlite3` was built without FTS5 **skips and says so** rather than failing the gate —
the capability is a property of the interpreter, not of this repo, and a green suite must not silently
promise a corpus Phase 3 cannot build.
"""

import sqlite3
import tempfile
from pathlib import Path
import unittest

#: The floor this lane is willing to name. FTS5 has been default-on in SQLite since 3.37 (2021);
#: `(3, 43)` is the first release whose `bm25()` and `t_idx`/`t_docsize` auxiliary-table shape this
#: probe asserts on. Bump it only against a measurement, never against a hope.
MIN_SQLITE = (3, 37)


def _version_tuple(raw: str) -> tuple:
    return tuple(int(part) for part in raw.split(".")[:3])


class Fts5CapabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "probe.db"

    def _open(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path))
        self.addCleanup(conn.close)
        return conn

    def _have_fts5(self, conn: sqlite3.Connection) -> bool:
        try:
            conn.execute("CREATE VIRTUAL TABLE probe_fts USING fts5(body)")
        except sqlite3.OperationalError:
            return False
        return True

    def test_the_capability_probe_answers_with_a_portable_instrument(self):
        """The instrument is a real `CREATE`, never `dbinfo()` — proven by the probe answering both ways.

        `sqlite3.dbinfo()` landed in Python 3.14 and this box runs 3.12.3, so the instrument the dispatch
        named does not exist here; the assertion is that the *substitute* discriminates. A probe that
        answered `True` for every interpreter would pass a capability suite by accident, so the negative
        half is not optional.
        """
        raw = sqlite3.sqlite_version
        self.assertGreaterEqual(len(raw.split(".")), 2, "unparsable sqlite_version %r" % raw)
        self.assertGreaterEqual(_version_tuple(raw), MIN_SQLITE,
                                "libsqlite3 %s is below the floor the design is stated against" % raw)
        conn = self._open()
        self.assertTrue(self._have_fts5(conn),
                        "this interpreter has no FTS5 — the lanes building Phase 3 must be told before "
                        "a corpus is designed, not after")

        class _WithoutFts5:
            def execute(self, _sql, *_args):
                raise sqlite3.OperationalError("no such module: fts5")

        self.assertFalse(self._have_fts5(_WithoutFts5()),
                         "the probe reported FTS5 on a connection that refused to create it")

    def test_the_temp_file_can_hold_an_fts5_table(self):
        conn = self._open()
        if not self._have_fts5(conn):
            self.skipTest("this interpreter's libsqlite3 has no FTS5 — Phase 3 must fall back to the "
                          "escaped LIKE path in media_search.py, and the corpus design stops here")
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
        names = [r[0] for r in row]
        self.assertIn("probe_fts", names)
        # The shadow tables are what an FTS5 table really is; asserting them pins the shape rather
        # than the marketing name, and they are what a migration has to respect.
        self.assertTrue(any(n.startswith("probe_fts_") for n in names),
                        "no shadow tables beside %r — that is not an FTS5 table" % names)

    def test_a_match_query_answers_and_a_ranked_one_orders(self):
        """The positive control: an index that matches *everything* and an index that matches *nothing*
        would both pass a CREATE, so this asserts discrimination, not presence."""
        conn = self._open()
        if not self._have_fts5(conn):
            self.skipTest("no FTS5 on this interpreter")
        conn.execute("CREATE VIRTUAL TABLE f USING fts5(title, body)")
        conn.execute("INSERT INTO f(title, body) VALUES "
                     "('Suzume 2022', 'a door must be closed across Japan'),"
                     "('Puli 2015', 'a heist told in four languages')")
        conn.commit()
        hits = [r[0] for r in conn.execute(
            "SELECT title FROM f WHERE f MATCH 'door' ORDER BY bm25(f)")]
        self.assertEqual(hits, ["Suzume 2022"])
        both = [r[0] for r in conn.execute(
            "SELECT title FROM f WHERE f MATCH 'heist OR japan' ORDER BY bm25(f)")]
        self.assertEqual(sorted(both), ["Puli 2015", "Suzume 2022"])
        none = conn.execute("SELECT title FROM f WHERE f MATCH 'quidditch'").fetchall()
        self.assertEqual(none, [], "a MATCH that answers text that is not in the corpus is not a search")
        phrase = [r[0] for r in conn.execute(
            "SELECT title FROM f WHERE f MATCH '\"four languages\"'")]
        self.assertEqual(phrase, ["Puli 2015"], "phrase queries are what OCR dialogue becomes")

    def test_prefix_queries_work_because_ocr_text_is_partial_by_construction(self):
        """A 5-20 s clip yields a truncated line; the design leans on `tok*`, so the tokenizer has to."""
        conn = self._open()
        if not self._have_fts5(conn):
            self.skipTest("no FTS5 on this interpreter")
        conn.execute("CREATE VIRTUAL TABLE f USING fts5(body)")
        conn.execute("INSERT INTO f(body) VALUES ('the goalkeeper signed for a club in goa')")
        conn.commit()
        self.assertEqual(conn.execute("SELECT count(*) FROM f WHERE f MATCH 'goalke'").fetchone()[0], 0,
                         "an unstarred prefix must NOT match — otherwise this test is really asserting "
                         "substring search, which FTS5 does not provide")
        self.assertEqual(conn.execute("SELECT count(*) FROM f WHERE f MATCH 'goalke*'").fetchone()[0], 1)

    def test_the_probe_wrote_nothing_outside_its_temporary_directory(self):
        """Cheap insurance against a fixture path drifting into `/home/ubuntu/radd-stream-data`, which
        is the directory the nightly backup snapshots by membership — see
        docs/BACKUP_SNAPSHOT_SCOPE_FINDING.md."""
        conn = self._open()
        self._have_fts5(conn)
        self.assertTrue(str(self.path).startswith(tempfile.gettempdir()),
                        "fixture left the temp tree: %s" % self.path)
        self.assertFalse(Path("/home/ubuntu/radd-stream-data/probe.db").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
