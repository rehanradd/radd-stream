#!/usr/bin/env python3
"""Price the #18 rebuild from the ledger's schema, without reading a single content row.

Why this file exists. `project_readonly.py` made the queued projection rebuild *safe to type* —
it refuses to create an output in the staging dir, in a protected dir, over an existing file, or
onto itself. It did not make the rebuild **sized**, and sizing is what #18 is actually waiting on.
The old answer to "how long is the rebuild" was "we will find out during it", on a 1-core box that
is also serving the API, against a 6.4 GB ledger. That is how the 22 GB of VACUUM snapshots in
`/tmp` happened.

What the code says, read instead of run (`catalog_v2.py:918`, `:1116`, `:1136`, `:1240`):

1. one head pass — `SELECT p.id AS post_id, p.* FROM posts p ORDER BY p.id` — which takes **every
   column of every post** and, through `_WorkAccumulator.absorb` (`catalog_v2.py:726`), **keeps every
   row alive** for the rest of the run. So the rebuild's cost is *resident memory*, not CPU-seconds,
   and it is bounded by the ledger's text, not by its row count;
2. three per-row lookups — `post_sources` by `post_id`, `releases` by `post_id` (twice sorted),
   `download_sources` by `release_id` — whose cost is decided entirely by whether the ledger has an
   index over that column. `fast_fetch.init_db` creates `idx_post_sources_post`, `idx_releases_post`
   and `idx_sources_rel`, so a ledger built by the engine walks an index. A staging vault or a
   hand-merged catalog might not, and the difference between an index walk and `SCAN posts` repeated
   146,176 times is the whole question.

The ruling this operates under (Muse, 09:07): a `mode=ro` **schema-only** open is LIGHT —
`sqlite_master` + `PRAGMA table_info` + `EXPLAIN QUERY PLAN`, no content-table rows, no writes.
`EXPLAIN QUERY PLAN` is the trick that makes this possible at all: SQLite plans a statement without
executing it, so the planner tells me `SEARCH releases USING INDEX idx_releases_post` or `SCAN posts`
and never touches a row. `recorded_statements` proves that claim mechanically — every SQL string this
tool sends the connection is a PRAGMA, a `sqlite_master` read, or an `EXPLAIN`.

The consequence of staying schema-only, stated plainly: **row counts are inputs, not measurements.**
Counting them is a content read, which stays FROZEN. So `--posts` / `--releases` / `--mean-row-bytes`
have to be typed in from a figure someone already measured (the code-recorded 146,176 posts is the
default, and it is labelled *recorded* because it is a quotation, not a fresh count), and a ledger
whose numbers nobody has recorded gets an `indeterminate` verdict instead of a guess.

Never a write, never a content row, and it says `indeterminate` rather than inventing a number.

    python3 -S Fast_Fetch/price_projection.py <ledger.db> --posts 146176 --releases 412000
    python3 -S Fast_Fetch/price_projection.py <ledger.db> --plan-only        # plan shape only
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import urllib.parse

#: The four Layer-0 statements `project()` issues, quoted from `catalog_v2.py` verbatim.
#: `test_price_projection.py` asserts each string is still literally in that file, so a refactor of
#: the projection breaks a test instead of quietly making this plan wrong.
STATEMENTS = (
    {"label": "head pass", "table": "posts", "join_column": None,
     "per": "once", "retains_rows": True,
     "sql": "SELECT p.id AS post_id, p.*\n        FROM posts p\n        ORDER BY p.id"},
    {"label": "sources per post", "table": "post_sources", "join_column": "post_id",
     "per": "post", "retains_rows": False,
     "sql": "SELECT source_site, url, source_title FROM post_sources WHERE post_id = ?"},
    {"label": "releases per post", "table": "releases", "join_column": "post_id",
     "per": "post", "retains_rows": False,
     "sql": "SELECT * FROM releases WHERE post_id = ? ORDER BY id"},
    {"label": "downloads per release", "table": "download_sources", "join_column": "release_id",
     "per": "release", "retains_rows": False,
     "sql": "SELECT * FROM download_sources WHERE release_id = ? ORDER BY id"},
)

#: The engine's own index law for those columns (`fast_fetch.init_db`), as a claim about what a
#: ledger built by `fast_fetch.py` should look like. A divergence is reported, never assumed away.
EXPECTED_INDEX = {"post_sources": "idx_post_sources_post",
                  "releases": "idx_releases_post",
                  "download_sources": "idx_sources_rel"}

#: Measured 2026-11-01 on this host: a synthetic ledger of 3,000 `posts` rows shaped like the
#: engine's own DDL (1,800 B synopsis), run through the head pass's retention pattern
#: (`SELECT p.id, p.* … ORDER BY p.id`, every row appended to a live list). RSS grew 17 → 23 MB while
#: 5,925,000 B of row text was retained, averaging 1,975 B/row; the file itself was 2,090 B/row.
#: The factor is coarse on purpose — `ru_maxrss` is a peak with 1 MB granularity on a 17 MB base — so
#: the model is "resident ≈ retained text, within about 10%", and `test_price_projection.py` checks
#: the published factor against the published raw numbers instead of trusting either.
CALIBRATION = {"synthetic_rows": 3000,
               "payload_bytes": 5_925_000,
               "payload_per_row_bytes": 1975,
               "rss_delta_mb": 6,
               "rss_mb_per_retained_mb": 1.01,
               "db_bytes_per_row": 2090,
               "synopsis_bytes": 1800,
               "columns": 19}

#: Quoted from the code, not counted here: `catalog_v2.py:968` records the ledger size the stats
#: endpoint was corrected against. A *recorded* figure, so the default is a citation and the verdict
#: says so rather than pretending it was measured this run.
RECORDED = {"posts": 146_176}

#: `project_readonly.py`'s law, kept identical: those files are never a target for projection work.
FORBIDDEN_NAMES = ("fast_fetch.db", "user_state.db", "resolvers.db")
FORBIDDEN_PREFIXES = ("merged_catalog_", "preapply_")

#: The floor the freeze instrument itself uses: at less than this much free memory, a rebuild that
#: retains the ledger is not started.
MIN_FREE_MB = 1500


class PricingRefused(RuntimeError):
    """The ledger is not something this tool may be pointed at."""


def open_schema_only(path):
    """A read-only handle, and the only handle this tool ever takes."""
    resolved = os.path.abspath(str(path))
    name = os.path.basename(resolved)
    if name in FORBIDDEN_NAMES or name.startswith(FORBIDDEN_PREFIXES):
        raise PricingRefused("%s is a production or snapshot file, not a pricing target" % name)
    uri = "file:" + urllib.parse.quote(resolved) + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.execute("PRAGMA query_only = ON")
    return conn


def table_names(conn):
    return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def index_map(conn, table):
    """index name -> the columns its CREATE statement covers, from `sqlite_master` text only."""
    out = {}
    for name, sql in conn.execute("SELECT name, sql FROM sqlite_master"
                                  " WHERE type='index' AND tbl_name=?", (table,)):
        out[name] = (sql or "").replace("\n", " ")
    return out


def plan(conn, sql):
    """`EXPLAIN QUERY PLAN` for one statement: what SQLite would do, without doing it.

    The placeholders are bound to NULL because the *plan* is what is being asked for, and SQLite will
    not answer that question about a statement with unfilled slots. A NULL binding never reaches a
    row: nothing executes.
    """
    rows = list(conn.execute("EXPLAIN QUERY PLAN " + sql, [None] * sql.count("?")))
    detail = " | ".join(str(r[3]) for r in rows)
    kind = "SCAN" if "SCAN " in detail and "WITHOUT INDEX" in detail else (
        "SCAN" if detail.startswith("SCAN ") or " SCAN " in detail else "SEARCH")
    if "TEMP B-TREE FOR ORDER BY" in detail:
        kind += "+sort"
    return kind, detail


def columns(conn, table):
    return [row[1] for row in conn.execute("PRAGMA table_info(%s)" % table)]


def price(conn, *, posts=None, releases=None, mean_row_bytes=None,
          free_mb=None, plan_only=False):
    """The plan shape, the nested-statement count, and the memory the head pass retains."""
    have = table_names(conn)
    missing = [s["table"] for s in STATEMENTS if s["table"] not in have]
    if missing:
        raise PricingRefused("no Layer-0 table(s): %s" % ", ".join(missing))

    rows = []
    for stmt in STATEMENTS:
        table = stmt["table"]
        indexes = index_map(conn, table)
        join = stmt["join_column"]
        covering = sorted(name for name, sql in indexes.items()
                          if join and join in sql)
        kind, detail = plan(conn, stmt["sql"])
        expected = EXPECTED_INDEX.get(table)
        rows.append({"label": stmt["label"], "table": table, "per": stmt["per"],
                     "join_column": join, "retains_rows": stmt["retains_rows"],
                     "plan": kind, "detail": detail,
                     "indexes": sorted(indexes), "covering_join": covering,
                     "matches_engine_ddl": (None if expected is None
                                            else expected in indexes)})

    result = {"ledger_statements": rows,
              "nested_statement_count": None,
              "retention": None,
              "verdict": "indeterminate",
              "why": []}

    if not plan_only:
        if posts is None:
            result["why"].append("no --posts: a row count is a content read, and content reads are"
                                 " frozen, so it must be typed in from a measurement someone made")
        else:
            rel = releases if releases is not None else 0
            n = 1 + 2 * int(posts) + int(rel)
            result["nested_statement_count"] = n
            result["why"].append("%d statements issued (%d posts × 2 lookups + %d release lookups)"
                                 % (n, int(posts), int(rel)))
            head = next(r for r in rows if r["label"] == "head pass")
            if not head["retains_rows"]:
                result["why"].append("the head pass no longer retains rows, so this model is stale")
            elif mean_row_bytes is None:
                result["retention"] = {"posts": int(posts),
                                       "mean_row_bytes": None,
                                       "estimated_retained_mb": None}
                result["why"].append("no --mean-row-bytes: retained cost is the ledger's TEXT volume"
                                     " (1,800 B of synopsis moves the number that a 40 B title does"
                                     " not), and page bytes for one table cannot be read without"
                                     " dbstat or a scan")
            else:
                retained_mb = int(posts) * int(mean_row_bytes) \
                    * CALIBRATION["rss_mb_per_retained_mb"] / 1e6
                free = free_mb if free_mb is not None else mem_available_mb()
                result["retention"] = {"posts": int(posts),
                                       "mean_row_bytes": int(mean_row_bytes),
                                       "rss_mb_per_retained_mb":
                                           CALIBRATION["rss_mb_per_retained_mb"],
                                       "calibration_payload_per_row_bytes":
                                           CALIBRATION["payload_per_row_bytes"],
                                       "estimated_retained_mb": round(retained_mb, 1),
                                       "free_mb": free}
                if free is None:
                    result["why"].append("free memory unknown and no --free-mb given")
                elif retained_mb + MIN_FREE_MB <= free:
                    result["verdict"] = "fits"
                    result["why"].append("retains ~%.0f MB with ~%.0f MB free (floor %d MB)"
                                         % (retained_mb, free, MIN_FREE_MB))
                else:
                    result["verdict"] = "does not fit"
                    result["why"].append("retains ~%.0f MB against ~%.0f MB free; the head pass has"
                                         " to be staged before this runs" % (retained_mb, free))

    #: `SCAN` is the *answer* for the head pass — it is one deliberate full pass, and no index would
    #: make `SELECT p.*` cheaper. A scan on a per-post or per-release lookup is the catastrophe: it
    #: means the ledger has no index over the join column and the rebuild scans the table once per
    #: row of the outer loop.
    hot_scans = [r["label"] for r in rows
                 if r["per"] != "once" and r["plan"].startswith("SCAN")]
    if hot_scans:
        if result["verdict"] == "fits":
            result["verdict"] = "does not fit"
        result["why"].append("full-table scans on the hot path: %s — the rebuild would scan that"
                             " table once per outer row" % ", ".join(hot_scans))
    drift = [r["label"] for r in rows if r["matches_engine_ddl"] is False]
    if drift:
        result["why"].append("index drift from the engine's own DDL: %s" % ", ".join(drift))
    return result


def mem_available_mb():
    """MemAvailable from /proc/meminfo — a host reading, not a database reading."""
    try:
        with open("/proc/meminfo", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
    except OSError:
        return None
    return None


def record_schema_only(conn):
    """Install a recorder and return the list it fills.

    This is how "no content row was read" is proved rather than claimed: every statement the caller
    then sends through this connection lands in the list, and the list can be checked against the
    schema-only grammar (`PRAGMA`, a `sqlite_master` read, or `EXPLAIN QUERY PLAN`). Call it *before*
    `price()` — a trace callback cannot retroactively record what already ran.
    """
    seen = []
    conn.set_trace_callback(seen.append)
    return seen


#: The three statement shapes a LIGHT open is allowed to send. `PRAGMA table_info(posts)` names a
#: Layer-0 table and reads no row of it, which is exactly the distinction the ruling turns on, so
#: PRAGMA is allowed by prefix rather than by table.
SCHEMA_ONLY_PREFIXES = ("EXPLAIN QUERY PLAN", "PRAGMA")


#: The four tables `project()` reads. `project_readonly.py` calls the same set `LAYER0`.
LAYER0_TABLES = ("posts", "releases", "download_sources", "post_sources")


def is_schema_only(sql):
    """True for a statement that cannot read a content row.

    Anything else is a content read, and content reads are frozen — including a `SELECT` that names a
    Layer-0 table anywhere outside an `EXPLAIN` prefix. This predicate is the ruling encoded rather
    than described, and `test_price_projection.py` runs every recorded statement through it.
    """
    text = " ".join(str(sql).split()).upper()
    if text.startswith(SCHEMA_ONLY_PREFIXES):
        return True
    if text.startswith("SELECT") and " FROM SQLITE_MASTER" in text:
        return not any("FROM %s" % table in text for table in LAYER0_TABLES)
    return False


def violations(statements):
    """The recorded statements that are not schema-only, for the report and the test alike."""
    return [sql for sql in statements if not is_schema_only(sql)]


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="price_projection.py",
        description="Price the v2 projection rebuild from a ledger's schema, without reading rows.")
    parser.add_argument("ledger", nargs="?", help="ledger to plan against, opened mode=ro")
    parser.add_argument("--posts", type=int, help="recorded post-row count (never counted here)")
    parser.add_argument("--releases", type=int, help="recorded release-row count")
    parser.add_argument("--mean-row-bytes", type=int,
                        help="mean retained text bytes per post row")
    parser.add_argument("--free-mb", type=int, help="override MemAvailable")
    parser.add_argument("--plan-only", action="store_true",
                        help="report the plan shape and no cost model at all")
    parser.add_argument("--default-posts", action="store_true",
                        help="use the code-recorded %d posts as the count" % RECORDED["posts"])
    args = parser.parse_args(argv)

    if not args.ledger:
        parser.print_usage(sys.stderr)
        print("[!] a ledger path is required; --default-posts still prices against a real schema",
              file=sys.stderr)
        return 2
    try:
        conn = open_schema_only(args.ledger)
    except (PricingRefused, sqlite3.Error) as exc:
        print("[!] refused: %s" % exc, file=sys.stderr)
        return 3
    recorded = record_schema_only(conn)
    try:
        posts = args.posts
        if posts is None and args.default_posts:
            posts = RECORDED["posts"]
            print("[i] --posts is the code-recorded %d from catalog_v2.py:968, a quotation and not"
                  " a measurement" % RECORDED["posts"])
        result = price(conn, posts=posts, releases=args.releases,
                       mean_row_bytes=args.mean_row_bytes, free_mb=args.free_mb,
                       plan_only=args.plan_only)
    except (PricingRefused, sqlite3.Error) as exc:
        conn.close()
        print("[!] refused: %s" % exc, file=sys.stderr)
        return 3
    conn.close()

    result["ledger_statements_sent"] = len(recorded)
    bad = violations(recorded)
    print(json.dumps(result, indent=1))
    if bad:
        print("[!] the LIGHT ruling was broken by: %s" % "; ".join(bad), file=sys.stderr)
        return 5
    print("[i] %d statements sent to the ledger, every one schema-only (PRAGMA / sqlite_master /"
          " EXPLAIN)" % len(recorded))
    print("[i] verdict: %s" % result["verdict"])
    for line in result["why"]:
        print("      - %s" % line)
    return 0 if result["verdict"] != "indeterminate" else 4


if __name__ == "__main__":
    sys.exit(main())
