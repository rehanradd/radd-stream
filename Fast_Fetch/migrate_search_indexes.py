#!/usr/bin/env python3
"""Reviewed migration: the two indexes the by-media search measurement asked for.

Written against the Q3-SEARCH-LATENCY brief's item E — *"do not create an index on the
production catalog by hand on the live service; put the production index/FTS build into
a reviewed migration script with its own runtime estimate; I will schedule when it
runs."* Nothing in this file runs on its own, and nothing here is applied by the fix
that shipped: `media_search.py` answers from the query shape alone, so the catalog is
correct and fast before any of this is scheduled.

Two steps, deliberately separated because they are not the same kind of change:

1. **`idx_cat_work_sites_post`** — `cat_work_sites.post_id` is the v1↔v2 bridge and has
   no index (`catalog_v2.DDL` indexes `cat_releases.work_id` but not the bridge), so
   every by-media request scans 275 488 rows twice. A read-side index on a column
   nothing writes differently: no staleness risk, no trigger, no behaviour change.
2. **`posts_fts` (FTS5, external content) + its three sync triggers** — turns the
   `SCAN p` that walks 150 799 rows into an index lookup. This is the step with a cost
   outside itself: the triggers run on every `posts` write, so the ingest path pays for
   it, and an index that drifts from its content table answers *wrong* rather than
   slowly. It therefore ships with a `verify` that fails loudly, and with the rule
   below.

**`media_search` does not read `posts_fts`.** Deliberate, and it is the reason this can
be scheduled at leisure: an FTS index the code cannot query cannot be wrong in a way a
user sees, so a half-built or stale index during the rollout window is an operational
non-event. Switching the matcher over is a separate reviewed change with its own tests.

Additive only. No table is dropped, altered or recreated, every statement is
`IF NOT EXISTS`, and the target path must be named on the command line — this tool
never guesses where the catalog lives.

    python3 -S Fast_Fetch/migrate_search_indexes.py plan    --target PATH
    python3 -S Fast_Fetch/migrate_search_indexes.py apply   --target PATH [--with-fts] --execute
    python3 -S Fast_Fetch/migrate_search_indexes.py verify  --target PATH
    python3 -S Fast_Fetch/migrate_search_indexes.py rollback --target PATH --execute

Stdlib only, like everything else here. SQLite 3.45.1 on this host, which has FTS5.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sqlite3
import sys
import time
from pathlib import Path

#: Rows indexed per second, measured on a copy of the production catalog on this VM
#: (150 799 posts, one core, other lanes live). See CONTINUITY.md for the run that
#: produced it. The estimate is deliberately derived from a measurement rather than
#: from a reassuring sentence.
#: The `rebuild` statement alone ran 150,799 rows in 38.3 s (3,934 rows/s); the whole
#: `apply --execute` took 46.3 s wall, so the constant below is the honest end-to-end
#: rate and the estimate it produces is conservative by design.
MEASURED_FTS_ROWS_PER_SECOND = 3_260        # measured, copy of production, load 7.9
MEASURED_BRIDGE_INDEX_SECONDS = 0.9         # 275,488 cat_work_sites rows, load 7.3
#: Extra bytes the FTS index cost on the copy, per indexed row.
MEASURED_FTS_BYTES_PER_ROW = 61             # 9.2 MB for 150,799 rows
#: Microseconds added to one `posts` INSERT by the three sync triggers, measured as
#: 5,000 inserts on the copy: 5,308 us/row with triggers against 412 us/row without.
#: This is the migration's cost to the ingest path and the owner has to see it before
#: approving step 2, not after.
MEASURED_TRIGGER_MICROSECONDS_PER_INSERT = 5_308
MEASURED_INSERT_MICROSECONDS_WITHOUT_TRIGGERS = 412

#: Rough head-room multiplier: the build needs the index plus its sort/run buffers.
DISK_SAFETY_FACTOR = 2.5

FTS_TABLE = "posts_fts"
FTS_COLUMNS = ("clean_title", "title")
BRIDGE_INDEX = "idx_cat_work_sites_post"
TRIGGERS = ("posts_fts_ai", "posts_fts_ad", "posts_fts_au")

BRIDGE_SQL = (f"CREATE INDEX IF NOT EXISTS {BRIDGE_INDEX} "
              f"ON cat_work_sites(post_id)")

#: External content (`content='posts'`) stores the index but not the text, so the
#: table stays small and the row content is read back from `posts` at query time. The
#: three triggers are what keep the two in step; without them the index silently lies.
FTS_SQL = (f"CREATE VIRTUAL TABLE IF NOT EXISTS {FTS_TABLE} USING fts5("
           f"{', '.join(FTS_COLUMNS)}, content='posts', content_rowid='id', "
           f"tokenize='unicode61 remove_diacritics 2')")

TRIGGER_SQL = (
    f"CREATE TRIGGER IF NOT EXISTS {TRIGGERS[0]} AFTER INSERT ON posts BEGIN"
    f"  INSERT INTO {FTS_TABLE}(rowid, {', '.join(FTS_COLUMNS)})"
    f"  VALUES (new.id, new.clean_title, new.title); END",
    f"CREATE TRIGGER IF NOT EXISTS {TRIGGERS[1]} AFTER DELETE ON posts BEGIN"
    f"  INSERT INTO {FTS_TABLE}({FTS_TABLE}, rowid, {', '.join(FTS_COLUMNS)})"
    f"  VALUES ('delete', old.id, old.clean_title, old.title); END",
    f"CREATE TRIGGER IF NOT EXISTS {TRIGGERS[2]} AFTER UPDATE ON posts BEGIN"
    f"  INSERT INTO {FTS_TABLE}({FTS_TABLE}, rowid, {', '.join(FTS_COLUMNS)})"
    f"  VALUES ('delete', old.id, old.clean_title, old.title);"
    f"  INSERT INTO {FTS_TABLE}(rowid, {', '.join(FTS_COLUMNS)})"
    f"  VALUES (new.id, new.clean_title, new.title); END",
)


def _count(conn, table):
    try:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    except sqlite3.Error:
        return -1


#: Rows `verify` reads a token out of. Cheap enough to run against a 150 799-post
#: catalog on this VM (measured: the whole `verify` is inside the 46 s `apply`), and
#: spread across the id range rather than taken from one end, because the failure this
#: is looking for — a trigger that stopped firing during a scrape — is not clustered.
SAMPLE_ROWS = 25


def _sample_tokens(conn, posts: int) -> tuple:
    """(row ids whose token is missing from the index, number of rows sampled).

    Positional row access on purpose: this connection has no `row_factory`, and a
    migration that dies on a TypeError after indexing 150 799 rows is a migration that
    has to be re-run to find out that it works.
    """
    if posts <= 0:
        return [], 0
    rows = conn.execute("SELECT id, clean_title FROM posts"
                        " WHERE clean_title IS NOT NULL AND length(clean_title) > 4"
                        " ORDER BY id").fetchall()
    if not rows:
        return [], 0
    step = max(len(rows) // SAMPLE_ROWS, 1)
    picked = rows[::step][:SAMPLE_ROWS]
    newest = conn.execute("SELECT id, clean_title FROM posts"
                          " WHERE clean_title IS NOT NULL AND length(clean_title) > 4"
                          " ORDER BY id DESC LIMIT 10").fetchall()
    seen, misses, sampled = set(), [], 0
    for row in list(picked) + list(newest):
        pid = int(row[0])
        if pid in seen:
            continue
        seen.add(pid)
        sampled += 1
        words = re.findall(r"[A-Za-z]{4,}", str(row[1] or ""))
        if not words:
            continue
        try:
            hit = conn.execute(f"SELECT rowid FROM {FTS_TABLE} WHERE {FTS_TABLE} MATCH ?",
                               (f'"{words[0]}"',)).fetchone()
        except sqlite3.Error:
            # A damaged index raises; a raised exception is a failure, never a pass.
            misses.append(pid)
            continue
        if hit is None:
            misses.append(pid)
    return misses, sampled


def _has_table(conn, name):
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type IN ('table','view')"
                        " AND name = ?", (name,)).fetchone() is not None


def _has_index(conn, name):
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='index'"
                        " AND name = ?", (name,)).fetchone() is not None


def _has_trigger(conn, name):
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='trigger'"
                        " AND name = ?", (name,)).fetchone() is not None


def _fingerprint(target: Path) -> str:
    stat = target.stat()
    return (f"{target}  {stat.st_size / 1e9:.2f} GB  mtime {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(stat.st_mtime))}")


def open_target(value):
    """Refuse to guess. A migration that picks its own database is how the wrong one
    gets written to while a lane believes it is testing a copy."""
    target = Path(value).expanduser()
    if not target.is_file():
        raise SystemExit(f"ABORT: --target is not a file: {target}")
    return target


def fts5_available() -> bool:
    """Ask this SQLite build, not the version string — FTS5 can be a loadable module."""
    probe = sqlite3.connect(":memory:")
    try:
        probe.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
        return True
    except sqlite3.OperationalError:
        return False
    finally:
        probe.close()


def _free_bytes(path: Path) -> int:
    return shutil.disk_usage(str(path)).free


def plan(conn, target: Path, with_fts: bool) -> int:
    posts = _count(conn, "posts")
    bridge = _count(conn, "cat_work_sites")
    print(f"target        : {_fingerprint(target)}")
    print(f"sqlite        : library {sqlite3.sqlite_version}")
    print(f"posts         : {posts:,} rows")
    print(f"cat_work_sites: {bridge:,} rows")
    print(f"free disk     : {_free_bytes(target) / 1e9:.1f} GB")
    print()
    print("STEP 1  bridge index (read-side, no triggers, no behaviour change)")
    print(f"        present now : {'yes' if _has_index(conn, BRIDGE_INDEX) else 'no'}")
    print(f"        statement   : {BRIDGE_SQL}")
    if bridge >= 0 and MEASURED_BRIDGE_INDEX_SECONDS > 0:
        est = MEASURED_BRIDGE_INDEX_SECONDS * (bridge / 275_488.0)
        print(f"        estimate    : ~{est:.0f} s at load 1"
              f" (measured {MEASURED_BRIDGE_INDEX_SECONDS:.1f} s for {bridge:,} rows on this VM)")
    print()
    if not with_fts:
        print("STEP 2  FTS5     : not requested (pass --with-fts to include it)")
        return 0
    if not fts5_available():
        print("STEP 2  REFUSE: this SQLite build cannot create an fts5 virtual table")
        return 1
    print("STEP 2  FTS5 over (clean_title, title), external content, with sync triggers")
    print(f"        fts5 in build: yes")
    print(f"        present now : {'yes' if _has_table(conn, FTS_TABLE) else 'no'}")
    print(f"        triggers    : "
          f"{', '.join(t + ('=yes' if _has_trigger(conn, t) else '=no') for t in TRIGGERS)}")
    print(f"        statement   : {FTS_SQL}")
    for statement in TRIGGER_SQL:
        print(f"                      {statement}")
    if posts > 0:
        if MEASURED_FTS_ROWS_PER_SECOND > 0:
            est = posts / MEASURED_FTS_ROWS_PER_SECOND
            print(f"        estimate    : ~{est / 60:.1f} min at load 1"
                  f" (measured {MEASURED_FTS_ROWS_PER_SECOND:,.0f} rows/s on this VM)")
            need = posts * max(MEASURED_FTS_BYTES_PER_ROW, 1) * DISK_SAFETY_FACTOR
            print(f"        disk headroom required: ~{need / 1e9:.2f} GB "
                  f"(have {_free_bytes(target) / 1e9:.1f} GB)")
            if need > _free_bytes(target):
                print("        REFUSE: not enough free space for the build")
                return 1
        else:
            print("        estimate    : NOT MEASURED — run the copy measurement first")
    print()
    print("Cost outside itself: every INSERT/UPDATE/DELETE on `posts` gains trigger")
    print("work, so the ingest path pays it. Measured on the copy, 5,000 post inserts:")
    print(f"  with triggers    {MEASURED_TRIGGER_MICROSECONDS_PER_INSERT:,} us/row")
    print(f"  without triggers {MEASURED_INSERT_MICROSECONDS_WITHOUT_TRIGGERS:,} us/row")
    if posts > 0:
        extra = posts * (MEASURED_TRIGGER_MICROSECONDS_PER_INSERT
                         - MEASURED_INSERT_MICROSECONDS_WITHOUT_TRIGGERS) / 1e6
        print(f"  a {posts:,}-post bulk scrape would gain ~{extra / 60:.0f} min of write time")
    print("`verify` must be run after any bulk scrape that used its own writer, because")
    print("an index that drifts answers wrong.")
    print("Nothing in `Fast_Fetch` reads `posts_fts` yet, so step 2 is a pure capability:")
    print("it can be approved and rolled back without touching a live code path.")
    return 0


def _sqls(with_fts):
    out = [BRIDGE_SQL]
    if with_fts:
        out.append("INSERT INTO " + FTS_TABLE + "(" + FTS_TABLE + ") VALUES('rebuild')")
        out.extend(TRIGGER_SQL)
    return out


def apply_migration(conn, target: Path, with_fts: bool, execute: bool) -> int:
    statements = _sqls(with_fts)
    if not execute:
        print("DRY RUN — nothing was written. Re-run with --execute to apply.")
        for statement in statements:
            print(f"  {statement}")
        return 0
    journal = conn.execute("PRAGMA journal_mode").fetchone()[0]
    print(f"journal mode  : {journal}   (this build writes; a scrape must not be running)")
    if with_fts and not _has_table(conn, FTS_TABLE):
        print(f"creating      : {FTS_TABLE}")
        conn.execute(FTS_SQL)
        conn.commit()
    started = time.perf_counter()
    if not _has_index(conn, BRIDGE_INDEX):
        conn.execute(BRIDGE_SQL)
        conn.commit()
        print(f"step 1        : {BRIDGE_INDEX} built in {time.perf_counter() - started:.1f} s")
    else:
        print(f"step 1        : {BRIDGE_INDEX} already present — skipped")
    if with_fts:
        # Rebuild first, triggers second. An external-content index is recomputed from
        # `posts` by `rebuild`, so a write that fires a trigger while the rebuild is
        # walking the table gets counted twice; in the other order the window is a
        # rebuild that misses a row, and `verify` catches that. The tests in
        # test_migrate_search_indexes.py pin the trigger behaviour after this point.
        started = time.perf_counter()
        conn.execute("INSERT INTO " + FTS_TABLE + "(" + FTS_TABLE + ") VALUES('rebuild')")
        conn.commit()
        took = time.perf_counter() - started
        rows = _count(conn, "posts")
        print(f"step 2        : rebuild of {rows:,} rows took {took:.1f} s"
              f" ({rows / max(took, 0.001):,.0f} rows/s)")
        for statement in TRIGGER_SQL:
            conn.execute(statement)
        conn.commit()
        print(f"                triggers {', '.join(TRIGGERS)} installed")
    return verify(conn, target, with_fts)


def verify(conn, target: Path, with_fts: bool) -> int:
    """The index must be provably in step with the ledger, or it is a liability."""
    failures = []
    print()
    print("VERIFY")
    if _has_index(conn, BRIDGE_INDEX):
        print(f"  {BRIDGE_INDEX:24} present")
    else:
        failures.append(f"{BRIDGE_INDEX} missing")
    if not with_fts:
        print("  posts_fts              not part of this run")
        print("  RESULT                 " + ("OK" if not failures else "; ".join(failures)))
        return 1 if failures else 0
    if not _has_table(conn, FTS_TABLE):
        failures.append("posts_fts missing")
    else:
        posts = _count(conn, "posts")
        print(f"  rows in posts          {posts:,}")
        # Two measured facts, both of which retire a check a reviewer would ask for:
        #
        #   `SELECT COUNT(*) FROM posts_fts` reads `posts`, not the index. Inserting
        #   past a dropped trigger left it at 21 while the index held 20.
        #   `INSERT INTO posts_fts(posts_fts) VALUES('integrity-check')` returned no
        #   error on that same mismatched database.
        #
        # So the honest number is the shadow table's own row count, and a token from a
        # sampled row is the proof — deleting the index outright corrupts the shadow
        # tables, which the sample catches as an exception rather than as a clean pass.
        docsize = _count(conn, f"{FTS_TABLE}_docsize")
        print(f"  index rows ({FTS_TABLE}_docsize): {docsize:,}")
        if posts >= 0 and docsize >= 0 and posts != docsize:
            failures.append(f"index holds {docsize} rows, posts holds {posts}")
        for t in TRIGGERS:
            if not _has_trigger(conn, t):
                failures.append(f"trigger {t} missing")
        misses = _sample_tokens(conn, posts)
        print(f"  token spot check       {misses[1]} rows sampled, {len(misses[0])} not findable")
        if misses[0]:
            failures.append(f"FTS cannot find a token from rows {misses[0][:6]}"
                            + (f" (+{len(misses[0]) - 6} more)"
                               if len(misses[0]) > 6 else ""))
    print("  RESULT                 " + ("OK" if not failures else "; ".join(failures)))
    return 1 if failures else 0


def rollback(conn, target: Path, execute: bool) -> int:
    """Only safe because nothing reads `posts_fts`: see the module docstring."""
    statements = [f"DROP TRIGGER IF EXISTS {t}" for t in TRIGGERS]
    statements.append(f"DROP TABLE IF EXISTS {FTS_TABLE}")
    if not execute:
        print("DRY RUN — nothing was dropped. Re-run with --execute.")
        for statement in statements:
            print(f"  {statement}")
        print("  (the bridge index is left in place: it is a plain read-side index)")
        return 0
    for statement in statements:
        conn.execute(statement)
    conn.commit()
    print(f"dropped: {', '.join(TRIGGERS)}, {FTS_TABLE}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=("plan", "apply", "verify", "rollback"))
    parser.add_argument("--target", required=True, type=open_target,
                        help="path to the catalog database — required, never guessed")
    parser.add_argument("--with-fts", action="store_true",
                        help="include step 2 (FTS5 + triggers); default is step 1 only")
    parser.add_argument("--execute", action="store_true",
                        help="actually write; without it apply/rollback are dry runs")
    args = parser.parse_args(argv)

    target = Path(args.target)
    conn = sqlite3.connect(str(target))
    try:
        if args.action == "plan":
            return plan(conn, target, args.with_fts)
        if args.action == "apply":
            return apply_migration(conn, target, args.with_fts, args.execute)
        if args.action == "verify":
            return verify(conn, target, args.with_fts)
        return rollback(conn, target, args.execute)
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
