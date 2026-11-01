#!/usr/bin/env python3
"""Reviewed migration: the two indexes the by-media search measurement asked for.

Written against the Q3-SEARCH-LATENCY brief's item E — *"do not create an index on the
production catalog by hand on the live service; put the production index/FTS build into
a reviewed migration script with its own runtime estimate; I will schedule when it
runs."* Nothing in this file runs on its own, and nothing here is applied by the fix
that shipped: `media_search.py` answers from the query shape alone, so the catalog is
correct and fast before any of this is scheduled.

Two steps here, plus a third that this session added; deliberately separated because they
are not the same kind of change:

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
    python3 -S Fast_Fetch/migrate_search_indexes.py apply   --target PATH [--with-fts] [--with-works-fts] --execute
    python3 -S Fast_Fetch/migrate_search_indexes.py verify  --target PATH [--with-fts] [--with-works-fts]
    python3 -S Fast_Fetch/migrate_search_indexes.py rollback --target PATH [--with-works-fts] --execute

Stdlib only, like everything else here. SQLite 3.45.1 on this host, which has FTS5.

**Step 3, added by the Cine-Finder brief, and the finding that put it here.** The v2 read
layer has always narrowed its search candidates with `AND w.id IN (SELECT rowid FROM
cat_works_fts WHERE cat_works_fts MATCH :fts)` (`catalog_api.py:1132`), guarded by
`_has_table(conn, "cat_works_fts")` (`:1260`, `:1302`). Nothing in this repository creates
that table, and no test ever did — so that branch has never executed anywhere, the flag has
always been False, and v2 search has only ever run its own documented LIKE fallback. The
module comment says as much in the conditional tense ("If a `cat_works_fts` FTS5 table is
ever added by the projection…", `catalog_api.py:39`), which is why this is a gap and not a
bug: the accelerator was designed, named, and never built. Step 3 builds it.

Step 2's `posts_fts` cannot be renamed to fill the hole. Its rowids are `posts.id`; the
read layer compares against `cat_works.id`, and those two id spaces are unrelated. That is
the whole reason an external-content index has to name its content table and its rowid
column out loud, and it is the shape of defect that a name-only fix would have shipped.
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


#: Step 3 — the index the v2 read layer already asks for by name.
#:
#: `catalog_api._run_listing` narrows candidates with
#: `AND w.id IN (SELECT rowid FROM cat_works_fts WHERE cat_works_fts MATCH :fts)`
#: (`catalog_api.py:1132`) behind `_has_table(conn, "cat_works_fts")` (`:1260`, `:1302`).
#: No code in this repo has ever created that table and no test has ever created it, so
#: the branch is dead in production and unjudged in CI: the v2 search has always taken
#: the LIKE path it documents as the fallback. Step 2's `posts_fts` cannot be renamed to
#: fill the hole — its rowids are `posts.id` while `w.id` is `cat_works.id`, and the two
#: id spaces are unrelated, which is exactly the kind of "same name, different row" bug
#: an external-content index invites. So this table is its own, external content on
#: `cat_works` with `content_rowid='id'`.
#:
#: The columns are the text the ledger actually holds: title, original title, synopsis,
#: and the facet strings. **Synopsis is the point.** `viewer.py:2860` matches `q=`
#: against `clean_title`, `title` and `slug`, and the word `synopsis` appears nowhere in
#: any query in this repo (measured: it is only echoed at `catalog_api.py:1522`), so plot
#: text is stored, shown on a detail page, and searchable by nothing. A clip's dialogue
#: line or a one-line plot memory therefore has no server-side answer today, and this is
#: the minimum corpus that changes it. Two dimensions the feature spec names are NOT in
#: here because the ledger has no such text, and inventing them would be worse than
#: reporting them: subtitle/dialogue text (`download_sources.playback_type='subtitle'`
#: is a file pointer, not a transcript) and cast/actor names (no cast column exists in
#: any table in `Fast_Fetch`).
#:
#: No triggers, deliberately, against step 2's reasoning. `cat_works` is a projection
#: written in bulk by `catalog_v2.project()`, and the trigger cost step 2 measured on
#: `posts` — 5,308 us/row against 412 us/row — would charge roughly 12 minutes per
#: 150k-row projection to a table that is about to be rewritten anyway. The refresh is
#: therefore an explicit `rebuild` after a projection, and the failure mode of forgetting
#: it is the safe direction: the adult law is NOT delegated to this index.
#: `_run_listing` applies `_adult_clause("w")` to `cat_works` itself (`catalog_api.py:1106`)
#: and the MATCH clause only ever *narrows* that set, so a stale or half-built works
#: index can under-report and can never surface a flagged work.
#: `test_forgotten_rebuild_loses_a_result_and_verify_says_so` and
#: `test_a_flagged_work_in_the_index_still_cannot_be_listed` pin the two halves of that
#: sentence rather than leaving them as a comment.
WORKS_FTS_TABLE = "cat_works_fts"
WORKS_FTS_COLUMNS = ("title", "original_title", "synopsis", "genres",
                     "languages", "country", "industry", "work_type")
WORKS_FTS_SQL = (f"CREATE VIRTUAL TABLE IF NOT EXISTS {WORKS_FTS_TABLE} USING fts5("
                 f"{', '.join(WORKS_FTS_COLUMNS)}, content='cat_works', "
                 f"content_rowid='id', tokenize='unicode61 remove_diacritics 2',"
                 f" prefix='2 3')")
#: The read layer asks for a prefix match on every token (`"tok"*`, `catalog_api.py:1134`),
#: so `prefix='2 3'` is what makes that expression an index lookup instead of a scan of
#: the posting lists. It costs index bytes, which is what the disk headroom line is for.
WORKS_FTS_REBUILD = (f"INSERT INTO {WORKS_FTS_TABLE}({WORKS_FTS_TABLE})"
                     " VALUES('rebuild')")


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


def _plan_works(conn, target: Path) -> int:
    """STEP 3's report, shared by both `plan` paths so `--with-works-fts` alone still
    prints it. Returns 1 only where the build must be refused."""
    works = _count(conn, "cat_works")
    print()
    if not fts5_available():
        print("STEP 3  REFUSE: this SQLite build cannot create an fts5 virtual table")
        return 1
    print("STEP 3  FTS5 over the v2 work text, external content on `cat_works` —"
          " the table `catalog_api` already queries by name")
    print(f"        cat_works    : {works:,} rows"
          + ("  (projection absent — run catalog_v2.project first)" if works < 0 else ""))
    print(f"        columns      : {', '.join(WORKS_FTS_COLUMNS)}")
    print(f"        present now  : {'yes' if _has_table(conn, WORKS_FTS_TABLE) else 'no'}")
    print(f"        triggers     : none by design; refresh is an explicit `rebuild`")
    print(f"        statement    : {WORKS_FTS_SQL}")
    print()
    if works > 0 and MEASURED_FTS_ROWS_PER_SECOND > 0:
        est = works / MEASURED_FTS_ROWS_PER_SECOND
        print(f"        estimate     : ~{est / 60:.1f} min at load 1"
              f" (extrapolated from the measured {MEASURED_FTS_ROWS_PER_SECOND:,.0f} rows/s,"
              " which was two short title columns — synopsis is longer, so read this"
              " as a floor and re-measure on a copy before scheduling)")
        need = works * MEASURED_FTS_BYTES_PER_ROW * DISK_SAFETY_FACTOR
        print(f"        disk headroom  : ~{need / 1e9:.2f} GB"
              f" (have {_free_bytes(target) / 1e9:.1f} GB; 61 B/row was measured on titles"
              " only, synopsis + prefix will cost more)")
        if need > _free_bytes(target):
            print("        REFUSE: not enough free space for the build")
            return 1
    else:
        print("        estimate     : NOT MEASURED for this table — the rate above was"
              " titles-only on `posts`, and there is no synopsis-indexed measurement yet")
    print()
    print("Unlike step 2, this table is LIVE the moment it exists: `_has_table` flips")
    print("`catalog_api`'s search onto the MATCH path. That is why it carries its own")
    print("tests, and why rollback is safe in the other direction — the read layer")
    print("computes its cursor fingerprint without the MATCH clause (catalog_api.py:1129-1133),")
    print("so dropping the index degrades to the LIKE path mid-conversation without")
    print("invalidating a single cursor.")
    return 0


def plan(conn, target: Path, with_fts: bool, works_fts: bool = False) -> int:
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
        if not works_fts:
            return 0
        return _plan_works(conn, target)
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
    if not works_fts:
        print()
        print("STEP 3  cat_works_fts: not requested (pass --with-works-fts to include it)")
        return 0
    return _plan_works(conn, target)


def _sqls(with_fts, works_fts=False):
    out = [BRIDGE_SQL]
    if with_fts:
        out.append("INSERT INTO " + FTS_TABLE + "(" + FTS_TABLE + ") VALUES('rebuild')")
        out.extend(TRIGGER_SQL)
    if works_fts:
        # The `CREATE` is here too so a dry run shows every statement a real run writes;
        # `apply` runs it separately because the rebuild needs the table to exist first.
        out.append(WORKS_FTS_SQL)
        out.append(WORKS_FTS_REBUILD)
    return out


def apply_migration(conn, target: Path, with_fts: bool, execute: bool,
                    works_fts: bool = False) -> int:
    statements = _sqls(with_fts, works_fts)
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
    if works_fts:
        if _count(conn, "cat_works") < 0:
            print("step 3        : REFUSED — `cat_works` does not exist in this database."
                  " Run catalog_v2.project() first; an external-content index cannot be"
                  " built over a content table that is not there.")
            return 1
        if not _has_table(conn, WORKS_FTS_TABLE):
            print(f"creating      : {WORKS_FTS_TABLE}")
            conn.execute(WORKS_FTS_SQL)
            conn.commit()
        started = time.perf_counter()
        conn.execute(WORKS_FTS_REBUILD)
        conn.commit()
        took = time.perf_counter() - started
        rows = _count(conn, "cat_works")
        print(f"step 3        : rebuild of {rows:,} works took {took:.1f} s"
              f" ({rows / max(took, 0.001):,.0f} rows/s)")
        print("                no triggers installed — re-run `apply --with-works-fts"
              " --execute` (or the rebuild statement alone) after every projection.")
    return verify(conn, target, with_fts, works_fts)


def _verify_works(conn, failures) -> None:
    """Drift checks for the works index, appended to `verify`'s failure list.

    The two facts worth having are the ones step 2 had to learn the hard way: a
    `COUNT(*)` on an external-content table reads the *content* table, so it cannot see
    drift, and `integrity-check` returns clean on a mismatched database. The shadow
    `…_docsize` row count and a token sampled out of the long column are the honest
    probes, and here the sampled token comes from `synopsis` — the column this index
    exists to make searchable and the one nothing else in the repo queries.
    """
    works = _count(conn, "cat_works")
    print(f"  rows in cat_works      {works:,}")
    if not _has_table(conn, WORKS_FTS_TABLE):
        failures.append(f"{WORKS_FTS_TABLE} missing")
        return
    docsize = _count(conn, f"{WORKS_FTS_TABLE}_docsize")
    print(f"  index rows ({WORKS_FTS_TABLE}_docsize): {docsize:,}")
    if works >= 0 and docsize >= 0 and works != docsize:
        failures.append(f"index holds {docsize} rows, cat_works holds {works}"
                        " — run the rebuild")
    orphan = conn.execute(
        f"SELECT COUNT(*) FROM {WORKS_FTS_TABLE}_docsize d"
        f" LEFT JOIN cat_works w ON w.id = d.id WHERE w.id IS NULL").fetchone()[0]
    print(f"  orphan rowids          {int(orphan):,}")
    if int(orphan) > 0:
        # An orphan rowid is not merely untidy: `catalog_api` narrows with
        # `w.id IN (SELECT rowid …)`, so a rowid that no longer names a work can only
        # ever drop a result — but it is proof the content table moved under the index,
        # which is the condition that makes every other number here untrustworthy.
        failures.append(f"{int(orphan)} indexed rowid(s) name no cat_works row")
    misses = _sample_works_tokens(conn, works)
    print(f"  synopsis spot check    {misses[1]} works sampled,"
          f" {len(misses[0])} not findable")
    if misses[0]:
        failures.append(f"FTS cannot find a synopsis token from works {misses[0][:6]}"
                        + (f" (+{len(misses[0]) - 6} more)"
                           if len(misses[0]) > 6 else ""))


def _sample_works_tokens(conn, works: int) -> tuple:
    """(work ids whose synopsis token is missing from the index, rows sampled)."""
    if works <= 0:
        return [], 0
    rows = conn.execute("SELECT id, synopsis FROM cat_works"
                        " WHERE synopsis IS NOT NULL AND length(synopsis) > 20"
                        " ORDER BY id").fetchall()
    if not rows:
        return [], 0
    step = max(len(rows) // SAMPLE_ROWS, 1)
    picked = rows[::step][:SAMPLE_ROWS]
    newest = conn.execute("SELECT id, synopsis FROM cat_works"
                          " WHERE synopsis IS NOT NULL AND length(synopsis) > 20"
                          " ORDER BY id DESC LIMIT 10").fetchall()
    seen, misses, sampled = set(), [], 0
    for row in list(picked) + list(newest):
        wid = int(row[0])
        if wid in seen:
            continue
        seen.add(wid)
        sampled += 1
        words = re.findall(r"[A-Za-z]{4,}", str(row[1] or ""))
        if not words:
            continue
        try:
            found = conn.execute(
                f"SELECT 1 FROM {WORKS_FTS_TABLE} WHERE rowid = ?"
                f" AND {WORKS_FTS_TABLE} MATCH ?", (wid, f'"{words[0]}"')).fetchone()
        except sqlite3.Error:
            return [wid], sampled
        if found is None:
            misses.append(wid)
    return misses, sampled


def verify(conn, target: Path, with_fts: bool, works_fts: bool = False) -> int:
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
    elif not _has_table(conn, FTS_TABLE):
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
    if works_fts:
        _verify_works(conn, failures)
    else:
        print("  cat_works_fts          not part of this run")
    print("  RESULT                 " + ("OK" if not failures else "; ".join(failures)))
    return 1 if failures else 0


def rollback(conn, target: Path, execute: bool, works_fts: bool = False) -> int:
    """Only safe because nothing reads `posts_fts`: see the module docstring.

    `cat_works_fts` is safe to drop for the *opposite* reason, and the difference is the
    one thing a reviewer should check before approving step 3: `catalog_api` does read it
    the moment it exists, but its cursor fingerprint is computed without the MATCH clause
    (`catalog_api.py:1129-1133`), so dropping the table mid-conversation degrades the
    search to the documented LIKE path rather than breaking any cursor in flight.
    """
    statements = [f"DROP TRIGGER IF EXISTS {t}" for t in TRIGGERS]
    statements.append(f"DROP TABLE IF EXISTS {FTS_TABLE}")
    if works_fts:
        statements.append(f"DROP TABLE IF EXISTS {WORKS_FTS_TABLE}")
    if not execute:
        print("DRY RUN — nothing was dropped. Re-run with --execute.")
        for statement in statements:
            print(f"  {statement}")
        print("  (the bridge index is left in place: it is a plain read-side index)")
        return 0
    for statement in statements:
        conn.execute(statement)
    conn.commit()
    dropped = ", ".join(TRIGGERS) + ", " + FTS_TABLE
    if works_fts:
        dropped += ", " + WORKS_FTS_TABLE
    print(f"dropped: {dropped}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=("plan", "apply", "verify", "rollback"))
    parser.add_argument("--target", required=True, type=open_target,
                        help="path to the catalog database — required, never guessed")
    parser.add_argument("--with-fts", action="store_true",
                        help="include step 2 (FTS5 + triggers); default is step 1 only")
    parser.add_argument("--with-works-fts", action="store_true",
                        help="include step 3 (cat_works_fts over the v2 work text, no"
                             " triggers); this is the index catalog_api already names")
    parser.add_argument("--execute", action="store_true",
                        help="actually write; without it apply/rollback are dry runs")
    args = parser.parse_args(argv)

    target = Path(args.target)
    conn = sqlite3.connect(str(target))
    try:
        if args.action == "plan":
            return plan(conn, target, args.with_fts, args.with_works_fts)
        if args.action == "apply":
            return apply_migration(conn, target, args.with_fts, args.execute,
                                   args.with_works_fts)
        if args.action == "verify":
            return verify(conn, target, args.with_fts, args.with_works_fts)
        return rollback(conn, target, args.execute, args.with_works_fts)
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
