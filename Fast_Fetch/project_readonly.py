#!/usr/bin/env python3
"""Project the v2 catalog from the live ledger without writing to it.

`catalog_v2.project()` reads exactly four Layer-0 tables — `posts`, `releases`,
`download_sources`, `post_sources` — and writes only `cat_*`. This driver binds
those four names to TEMP VIEWs over an ATTACHed read-only copy of the production
file, so the source is opened `mode=ro` (plus `PRAGMA query_only`) and every
write lands in `--out`, a new file. The running service keeps its catalog.

Usage:
    python3 -S project_readonly.py SRC OUT
"""
import json
import os
import sqlite3
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import catalog_v2  # noqa: E402

LAYER0 = ("posts", "releases", "download_sources", "post_sources")


def main(argv):
    if len(argv) != 3:
        print(__doc__.strip().splitlines()[-1], file=sys.stderr)
        return 2
    src, out = argv[1], argv[2]
    if os.path.abspath(src) == os.path.abspath(out):
        print("refusing to project a database onto itself", file=sys.stderr)
        return 2
    if os.path.exists(out):
        print(f"refusing to reuse an existing output: {out}", file=sys.stderr)
        return 2

    started = time.time()
    conn = sqlite3.connect(f"file:{out}?mode=rwc", uri=True)
    conn.row_factory = sqlite3.Row
    # URI processing is enabled on this connection, which is what lets ATTACH
    # parse the `mode=ro` query string below.
    conn.execute("ATTACH DATABASE ? AS src", (f"file:{src}?mode=ro",))
    ro = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    ro.execute("PRAGMA query_only=ON")
    print(f"[i] source {src} opened read-only; output {out}", flush=True)
    print("[i] source stamp: " + json.dumps({
        "posts": ro.execute("SELECT COUNT(*) FROM posts").fetchone()[0],
        "adult_rows": ro.execute("SELECT COUNT(*) FROM posts WHERE is_18_plus=1").fetchone()[0],
        "releases": ro.execute("SELECT COUNT(*) FROM releases").fetchone()[0],
        "download_sources": ro.execute("SELECT COUNT(*) FROM download_sources").fetchone()[0],
    }, sort_keys=True) + f" ({time.time() - started:.0f}s)", flush=True)

    for name in LAYER0:
        conn.execute(f"CREATE TEMP VIEW {name} AS SELECT * FROM src.{name}")

    # `PRAGMA journal_mode=DELETE` cannot run while a read-only WAL database is
    # ATTACHed (SQLite answers "disk I/O error"); a new file is already in delete
    # mode, so it is asserted rather than set.
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    if str(mode).lower() != "delete":
        print(f"unexpected journal mode on a new file: {mode}", file=sys.stderr)
        return 2
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-262144")   # 256 MB page cache for the output
    conn.execute("PRAGMA temp_store=FILE")      # no multi-GB RSS spike on the finalize sort

    summary = catalog_v2.project(conn, rev=None, verbose=True)
    print("[✓] projected in %.0fs: %s" % (time.time() - started, json.dumps(summary, sort_keys=True)),
          flush=True)

    # Verification, read-only against the source. `counters["links"]` is every
    # download_sources row the walk visited; `cat_links` is what survived
    # UNIQUE(release_id, url). Zero loss = walked == source rows, no orphan link
    # points at a source row that does not exist, and every source row not
    # carried as its own cat_links row still has its URL in the catalog.
    checks = {}
    checks["source_download_sources"] = ro.execute(
        "SELECT COUNT(*) FROM download_sources").fetchone()[0]
    checks["walked_links"] = summary["links"]
    checks["cat_links"] = conn.execute("SELECT COUNT(*) FROM cat_links").fetchone()[0]
    checks["orphan_cat_links"] = conn.execute(
        "SELECT COUNT(*) FROM cat_links l"
        " WHERE l.ledger_link_id IS NULL OR NOT EXISTS"
        " (SELECT 1 FROM src.download_sources d WHERE d.id = l.ledger_link_id)").fetchone()[0]
    conn.execute("CREATE TEMP TABLE missing (id INTEGER PRIMARY KEY, url TEXT)")
    conn.execute("INSERT INTO missing (id, url)"
                 " SELECT id, source_url FROM src.download_sources WHERE id NOT IN"
                 " (SELECT ledger_link_id FROM cat_links WHERE ledger_link_id IS NOT NULL)")
    checks["source_rows_not_carried_by_id"] = conn.execute(
        "SELECT COUNT(*) FROM missing").fetchone()[0]
    # URL lookups need an index that the projection itself does not build; it is
    # created in the OUTPUT file for the check and dropped again below.
    conn.execute("CREATE INDEX IF NOT EXISTS idx_verify_cat_links_url ON cat_links(url)")
    checks["source_rows_with_no_matching_url"] = conn.execute(
        "SELECT COUNT(*) FROM missing m WHERE m.url IS NOT NULL AND NOT EXISTS"
        " (SELECT 1 FROM cat_links l WHERE l.url = m.url)").fetchone()[0]
    checks["urls_recovered"] = (checks["source_rows_not_carried_by_id"]
                                - checks["source_rows_with_no_matching_url"])
    conn.execute("DROP INDEX idx_verify_cat_links_url")
    checks["stamped"] = dict(conn.execute(
        "SELECT key, value FROM cat_projection_meta").fetchall())
    print("[✓] verify: " + json.dumps(checks, sort_keys=True, default=str), flush=True)
    conn.commit()
    conn.close()
    ro.close()
    print(f"[✓] done in {time.time() - started:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
