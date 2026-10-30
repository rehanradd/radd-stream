#!/usr/bin/env python3
"""
test_dub_collision_census.py — how often title+year names two different prints.

Q2-DUB-COLLISION-CENSUS, 2026-10-30. ``canonical_key`` is
``generate_canonical_key(clean_title, year)`` (``fast_fetch.py:572``), and
themoviebox publishes a dubbed print as a separate subject with the same
title+year — so the key can name two different works.

Measured constraint that shapes the query: every staging database declares
``canonical_key`` PRIMARY KEY or UNIQUE (themoviebox/filmyhit ``TEXT PRIMARY
KEY``, hindilinks4u/world4ufree ``TEXT UNIQUE``). A dub twin therefore cannot
exist *inside* one staging database — the second subject with the same title+
year is either refused or collapses onto the first row. The collision is only
observable **across databases**, which is also the shape of the merged ledger
where ``canonical_key`` is a plain column and 442 keys carry both a flagged and
an unflagged row.

So the census is two-phase and index-only until it can be precise:

1. read each database's key set from the covering index on ``canonical_key``
   (no table pages, no sorts);
2. fetch languages/is_18_plus (point lookups through the same index) only for
   keys that appear in two or more databases.

Divergence is judged in Python after normalization: ``Hindi, English`` and
``English/Hindi`` are one audio set, not a collision. SQL's ``COUNT(DISTINCT
languages)`` would call them different.

Run the offline suite (what CI executes):

    python3 -S Fast_Fetch/importers/test_dub_collision_census.py

Run the census against the staging vaults (read-only; never the production
ledger). It refuses to scan while load1 is at or above the ceiling:

    python3 -S Fast_Fetch/importers/test_dub_collision_census.py --census
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import tempfile
import time
import unittest
from collections import Counter
from contextlib import closing
from pathlib import Path

DB_DIR = Path(os.environ.get("RADD_CENSUS_DB_DIR",
                             "/home/ubuntu/radd-stream-data"))

# The production ledger and the two 6 GB merge/pre-apply artifacts are named
# here so a mistaken --census can never walk into them.
NEVER_SCAN = {
    "fast_fetch.db", "fast_fetch_old_7mb_backup.db",
    "merged_catalog_20261025.db", "preapply_20261029_1726.db",
    "resolvers.db", "user_state.db",
}

# Second and third scrapes of the same site would double every key without
# adding a site, so the census reads one database per site.
DUPLICATE_SCRAPES = {
    "katmoviehd_refreshed.db": "katmoviehd.db",
    "mp4moviez_staging.db": "mp4moviez.db",
    "mp4moviez_staging2.db": "mp4moviez.db",
    "multimovies_full_20261022.db": "multimovies.db",
}

LOAD_CEILING = 4.0


def canon_site(db_name: str) -> str:
    """The site a staging database belongs to, by file name."""
    return db_name[:-3] if db_name.endswith(".db") else db_name


def norm_languages(text) -> str:
    """A language set as a sorted signature; order and spacing do not matter."""
    if not text:
        return ""
    parts = re.split(r"[,/;&|+]+|\band\b", str(text).casefold())
    tokens = sorted({part.strip(" .") for part in parts if part.strip(" .")})
    return "|".join(tokens)


def _columns(conn: sqlite3.Connection) -> set:
    return {row[1] for row in conn.execute("PRAGMA table_info(posts)")}


def _key_sql() -> str:
    return ("SELECT canonical_key FROM posts "
            "WHERE canonical_key IS NOT NULL AND canonical_key <> '' "
            "AND canonical_key <> 'unknown'")


def key_set(conn: sqlite3.Connection) -> set:
    """Every canonical_key in one database, read from the covering index.

    The plan is recorded by ``key_plan`` and printed in the census report: on
    every staging database measured, ``SEARCH posts USING COVERING INDEX`` —
    no table pages are touched here.
    """
    if "canonical_key" not in _columns(conn):
        return set()
    return {row[0] for row in conn.execute(_key_sql())}


def key_plan(conn: sqlite3.Connection) -> str:
    return " | ".join(str(row[3]) for row in conn.execute(
        "EXPLAIN QUERY PLAN " + _key_sql()))


def rows_for_key(conn: sqlite3.Connection, site: str, key: str):
    """The full rows behind one colliding key, as census tuples.

    A point lookup through the same index; one row per database in practice,
    several only in a database that holds more than one ``source_site``.
    """
    cols = _columns(conn)
    has_site = "source_site" in cols
    has_lang = "languages" in cols
    has_adult = "is_18_plus" in cols
    site_expr = "COALESCE(source_site, ?)" if has_site else "?"
    lang_expr = "substr(COALESCE(languages, ''), 1, 240)" if has_lang else "''"
    adult_expr = ("CASE WHEN COALESCE(is_18_plus, 0) = 1 THEN 1 ELSE 0 END"
                  if has_adult else "0")
    sql = ("SELECT " + site_expr + ", " + lang_expr + ", " + adult_expr
           + " FROM posts WHERE canonical_key = ?")
    for row_site, langs, adult in conn.execute(sql, (site, key)):
        yield (key, row_site or site, norm_languages(langs), 1, int(adult))


def census_rows(conns):
    """Flat census rows across ``(conn, site)`` pairs, two-phase and index-only.

    Phase 1 builds the key multiset from covering-index reads. Phase 2 fetches
    rows only for keys present in two or more databases. A key unique to one
    database cannot be a collision under the staging UNIQUE constraint, so it
    is never read from the table.
    """
    db_keys = [(conn, site, key_set(conn)) for conn, site in conns]
    seen = Counter(key for _, _, keys in db_keys for key in keys)
    for conn, site, keys in db_keys:
        for key in keys:
            if seen[key] > 1:
                yield from rows_for_key(conn, site, key)


def summarize(rows):
    """Group flat census rows into per-key verdicts.

    ``rows`` is any iterable of ``(key, site, lang_sig, n, flagged)``. The
    verdict for a key is a dict; keys are returned in insertion order.
    """
    keys = {}
    for key, site, sig, n, flagged in rows:
        entry = keys.setdefault(key, {"sites": {}, "sigs": {}, "rows": 0,
                                      "flagged": 0})
        entry["sites"][site] = entry["sites"].get(site, 0) + n
        entry["sigs"][sig] = entry["sigs"].get(sig, 0) + n
        entry["rows"] += n
        entry["flagged"] += flagged * n
    out = {}
    for key, entry in keys.items():
        non_empty = [sig for sig in entry["sigs"] if sig]
        out[key] = {
            "rows": entry["rows"],
            "sites": sorted(entry["sites"]),
            "site_count": len(entry["sites"]),
            "flagged": entry["flagged"],
            "unflagged": entry["rows"] - entry["flagged"],
            "divergent": len(non_empty) > 1,
            "language_sets": sorted(entry["sigs"]),
        }
    return out


def counters(verdicts):
    """The report's headline numbers.

    Under the staging UNIQUE constraint a single database holds one row per
    key, so ``keys_with_more_than_one_row`` and ``keys_across_more_than_one_site``
    coincide for single-site databases; both are reported so a multi-source
    database cannot hide the difference.
    """
    total = len(verdicts)
    multi = {k: v for k, v in verdicts.items() if v["rows"] > 1}
    cross = {k: v for k, v in multi.items() if v["site_count"] > 1}
    divergent = {k: v for k, v in multi.items() if v["divergent"]}
    divergent_cross = {k: v for k, v in cross.items() if v["divergent"]}
    twins = {k: v for k, v in divergent.items()
             if v["flagged"] and v["unflagged"]}
    return {
        "keys": total,
        "keys_with_more_than_one_row": len(multi),
        "keys_across_more_than_one_site": len(cross),
        "divergent_keys": len(divergent),
        "divergent_keys_across_sites": len(divergent_cross),
        "divergent_keys_with_flagged_and_clean_rows": len(twins),
    }


def open_readonly(path: Path) -> sqlite3.Connection:
    """A connection that cannot write, even by mistake."""
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    conn.execute("PRAGMA query_only = 1")
    return conn


def load_average() -> float:
    try:
        return float(Path("/proc/loadavg").read_text().split()[0])
    except (OSError, ValueError, IndexError):
        return 0.0


def staging_databases(db_dir: Path = DB_DIR):
    """One database per site, production artifacts excluded."""
    out = []
    for path in sorted(db_dir.glob("*.db")):
        if path.name in NEVER_SCAN or path.name in DUPLICATE_SCRAPES:
            continue
        out.append(path)
    return out


def run_census(db_dir: Path = DB_DIR, examples: int = 15,
               load_ceiling: float = LOAD_CEILING, budget_s: float | None = None):
    """Read-only census. Returns a JSON-able report; stops cleanly on load.

    ``budget_s`` bounds the whole walk so a hot box is not held for minutes;
    the databases it did not reach are named in the report rather than silently
    dropped.
    """
    started = time.time()
    opened, scanned, skipped, stopped = [], [], [], None
    try:
        for path in staging_databases(db_dir):
            if load_average() >= load_ceiling:
                stopped = f"load1 {load_average():.2f} >= {load_ceiling}"
                break
            if budget_s is not None and time.time() - started >= budget_s:
                stopped = f"budget {budget_s:.0f}s exhausted"
                break
            conn = open_readonly(path)
            keys = key_set(conn)
            if not keys:
                conn.close()
                skipped.append({"db": path.name,
                                "error": "no posts table or no canonical_key"})
                continue
            scanned.append({"db": path.name, "keys": len(keys),
                            "plan": key_plan(conn)})
            opened.append((conn, canon_site(path.name)))
        verdicts = summarize(census_rows(opened))
    finally:
        for conn, _ in opened:
            conn.close()
    stats = counters(verdicts)
    ordered = sorted(
        ({"key": k, **v} for k, v in verdicts.items()
         if v["divergent"] or v["site_count"] > 1),
        key=lambda v: (not v["divergent"], not v["flagged"], -v["rows"], v["key"]))
    stats.update({
        "databases_scanned": len(scanned),
        "databases_skipped": skipped,
        "stopped": stopped,
        "wall_seconds": round(time.time() - started, 1),
        "examples": ordered[:examples],
        "scanned": scanned,
    })
    return stats


# ---------------------------------------------------------------------------
# Offline tests — fixtures only, no staging database and no network
# ---------------------------------------------------------------------------

def _fixture(rows) -> sqlite3.Connection:
    """A staging-shaped posts table: canonical_key is the PRIMARY KEY."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE posts (canonical_key TEXT PRIMARY KEY,"
                 " source_site TEXT, languages TEXT, is_18_plus INTEGER)")
    conn.executemany("INSERT OR IGNORE INTO posts VALUES (?, ?, ?, ?)", rows)
    return conn


class GroupingTests(unittest.TestCase):
    def test_staging_refuses_a_second_row_for_the_same_key(self):
        # The measured DDL: canonical_key PRIMARY KEY. The dub twin cannot live
        # beside the original here, which is why the census merges across DBs.
        conn = _fixture([("pushpa-2_2024", "themoviebox", "Hindi", 0),
                         ("pushpa-2_2024", "themoviebox", "Telugu", 0)])
        self.assertEqual(conn.execute("SELECT count(*) FROM posts").fetchone()[0], 1)

    def test_a_dub_on_one_site_and_the_original_on_another_are_divergent(self):
        dub = _fixture([("pushpa-2_2024", "themoviebox", "Hindi", 0)])
        original = _fixture([("pushpa-2_2024", "filmyhit", "Telugu", 0)])
        verdict = summarize(census_rows([(dub, "themoviebox"),
                                         (original, "filmyhit")]))["pushpa-2_2024"]
        self.assertEqual(verdict["site_count"], 2)
        self.assertTrue(verdict["divergent"],
                        "same key, two audio languages, two separate prints")

    def test_reordered_languages_are_not_a_collision(self):
        a = _fixture([("a_2020", "sitex", "Hindi, English", 0)])
        b = _fixture([("a_2020", "sitey", "english/hindi", 0)])
        verdict = summarize(census_rows([(a, "sitex"), (b, "sitey")]))["a_2020"]
        self.assertFalse(verdict["divergent"])
        self.assertEqual(verdict["language_sets"], ["english|hindi"])

    def test_a_key_on_two_sites_with_the_same_languages_is_not_divergent(self):
        a = _fixture([("b_2019", "sitex", "Hindi", 0)])
        b = _fixture([("b_2019", "sitey", "Hindi", 0)])
        stats = counters(summarize(census_rows([(a, "sitex"), (b, "sitey")])))
        self.assertEqual(stats["keys_across_more_than_one_site"], 1)
        self.assertEqual(stats["divergent_keys_across_sites"], 0)

    def test_a_database_with_a_unique_key_only_reads_its_index(self):
        conn = _fixture([("c_2018", "sitex", "Hindi", 0)])
        self.assertIn("USING COVERING INDEX", key_plan(conn))

    def test_a_missing_languages_column_is_an_empty_signature(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE posts (canonical_key TEXT PRIMARY KEY,"
                     " source_site TEXT)")
        conn.executemany("INSERT INTO posts VALUES (?, ?)",
                         [("c_2018", "sitex"), ("c_2017", "sitey")])
        self.assertEqual(key_set(conn), {"c_2018", "c_2017"})
        row = list(rows_for_key(conn, "sitex", "c_2018"))[0]
        self.assertEqual(row, ("c_2018", "sitex", "", 1, 0))

    def test_a_database_without_canonical_key_is_skipped_loudly(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE posts (title TEXT)")
        self.assertEqual(key_set(conn), set())

    def test_unknown_and_empty_keys_are_ignored(self):
        conn = _fixture([("unknown", "sitex", "Hindi", 0),
                         ("", "sitex", "Hindi", 0),
                         (None, "sitex", "Hindi", 0)])
        self.assertEqual(key_set(conn), set())


class VerdictTests(unittest.TestCase):
    def test_the_adult_twin_is_flagged_and_clean_rows_under_one_key(self):
        verdicts = summarize([
            ("d_2017", "themoviebox", "hindi", 1, 1),
            ("d_2017", "themoviebox", "telugu", 1, 0),
        ])
        stats = counters(verdicts)
        self.assertEqual(stats["divergent_keys_with_flagged_and_clean_rows"], 1)

    def test_two_flagged_rows_are_not_a_twin(self):
        verdicts = summarize([
            ("e_2016", "sitex", "hindi", 1, 1),
            ("e_2016", "sitex", "telugu", 1, 1),
        ])
        self.assertEqual(counters(verdicts)["divergent_keys_with_flagged_and_clean_rows"], 0)

    def test_a_single_row_is_never_a_collision(self):
        verdicts = summarize([("f_2015", "sitex", "hindi", 1, 0)])
        self.assertEqual(counters(verdicts)["divergent_keys"], 0)


class ReadOnlyTests(unittest.TestCase):
    def test_the_census_connection_refuses_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "v.db"
            conn = sqlite3.connect(path)
            conn.execute("CREATE TABLE posts (canonical_key TEXT)")
            conn.commit()
            conn.close()
            with closing(open_readonly(path)) as ro:
                with self.assertRaises(sqlite3.OperationalError):
                    ro.execute("DELETE FROM posts")
                ro.execute("SELECT count(*) FROM posts").fetchone()

    def test_the_production_ledger_is_never_scanned(self):
        self.assertIn("fast_fetch.db", NEVER_SCAN)
        self.assertIn("merged_catalog_20261025.db", NEVER_SCAN)
        self.assertIn("preapply_20261029_1726.db", NEVER_SCAN)
        self.assertIn("multimovies_full_20261022.db", DUPLICATE_SCRAPES)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--census" not in argv:
        unittest.main(argv=[sys.argv[0]] + [a for a in argv if a.startswith("-v")])
        return 0
    report = run_census()
    json.dump(report, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    return 2 if report["stopped"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
