#!/usr/bin/env python3
"""Project the v2 catalog from the live ledger without writing to it.

`catalog_v2.project()` reads exactly four Layer-0 tables — `posts`, `releases`,
`download_sources`, `post_sources` — and writes only `cat_*`. This driver binds
those four names to TEMP VIEWs over an ATTACHed read-only copy of the production
file, so the source is opened `mode=ro` (plus `PRAGMA query_only`) and every
write lands in OUT, a new file. The running service keeps its catalog.

OUT is validated before anything is opened (`resolve_target`): it may not be the
source, may not already exist, may not be named like a catalog or a merge
snapshot, and may not sit inside the staging data dir — a fresh `.db` there would
join the merge's input glob and be read as a catalog by the next lane.

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

#: Names that belong to a catalog, a merge snapshot, or a credential store — never to a rebuild
#: output, wherever it is written. A lane that globs `*.db` in the data dir cannot tell a fresh
#: projection from the file it is named like.
FORBIDDEN_NAMES = ("fast_fetch.db", "user_state.db", "resolvers.db")
FORBIDDEN_PREFIXES = ("merged_catalog_", "preapply_")


class TargetRefused(RuntimeError):
    """The output path is one this driver must not create, so nothing is opened."""


def protected_dirs():
    """Directories a projection output must never be created inside.

    Total by design: `config` is asked inside the guard, and an import that fails — including the
    EACCES-on-`/home/ubuntu` shape that ended a hosted run at q5's `eb4c0ee` — falls back to the
    literal host paths. An unreadable mount is never a licence to write beside the live catalog.
    Nothing here stats or opens anything; these are strings until `resolve_target` compares them.
    """
    dirs = ["/home/ubuntu/radd-stream-data"]
    try:
        import config
        dirs += [str(config.DATA_DIR), os.path.dirname(str(config.DB_PATH))]
    except Exception:
        pass
    return [os.path.abspath(d) for d in dirs]


def resolve_target(src, out, protected=None):
    """Turn two operator-supplied paths into the two the driver will actually use, or refuse.

    The standing hazard rule is "print the resolved target before any write and stop if it names the
    merged catalog or anything under the staging data dir". Until now the only checks were
    same-file and exists — which is why `OUT=/home/ubuntu/radd-stream-data/scratch.db`, a path the
    driver happily accepts today, would have dropped a new file into the merge's input glob.

    A rebuild beside its own source in a *scratch* directory stays legal: that is exactly how
    `test_project_readonly.py` runs, and a guard that refused it would be a guard nobody can use.
    """
    src_abs, out_abs = os.path.abspath(src), os.path.abspath(out)
    if src_abs == out_abs:
        raise TargetRefused("refusing to project a database onto itself: %s" % src_abs)
    name = os.path.basename(out_abs)
    if name in FORBIDDEN_NAMES or name.startswith(FORBIDDEN_PREFIXES):
        raise TargetRefused("%s names a catalog, a merge snapshot or a credential store; give a "
                            "rebuild output a name a lane can tell apart" % out_abs)
    if os.path.exists(out_abs):
        raise TargetRefused("refusing to reuse an existing output: %s" % out_abs)
    for directory in (protected_dirs() if protected is None else protected):
        prefix = os.path.abspath(directory).rstrip(os.sep) + os.sep
        if out_abs == os.path.abspath(directory) or out_abs.startswith(prefix):
            raise TargetRefused(
                "%s is inside %s — that directory holds the live catalog and the merge's inputs, "
                "and a NEW .db created there is read as a catalog by the next lane and added to "
                "q3's copy glob. Project into a scratch directory instead."
                % (out_abs, os.path.abspath(directory)))
    return src_abs, out_abs


def main(argv):
    if len(argv) != 3:
        print(__doc__.strip().splitlines()[-1], file=sys.stderr)
        return 2
    try:
        src, out = resolve_target(argv[1], argv[2])
    except TargetRefused as exc:
        print(f"[!] {exc}", file=sys.stderr)
        return 2
    print(f"[i] resolved target before any write: source={src} (mode=ro) out={out}", flush=True)

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
