#!/usr/bin/env python3
"""Read-only inventory of the per-site staging databases.

The fleet has been writing staging catalogs for weeks with two different schema
generations in the same directory: the older sites keep their links in
``download_sources``/``post_sources`` and have no ``sources`` table at all, while the
newest importers write ``sources`` with ``playback_type``/``status`` and a ``raw_meta``
JSON blob on ``posts``. Any plan that assumes one shape therefore silently reads zeros
out of the other. This tool answers, per database, which shape it actually is, how many
rows each table holds, and what cannot be measured because a column was never created.

Read-only by construction: every connection is opened as ``file:<path>?mode=ro``, the
only statements issued are ``SELECT``/``PRAGMA table_info``, and a database that cannot
be opened is reported as a warning rather than retried with a writable handle.

Be precise about what "never write" covers: a read-only connection cannot modify the
main ``.db`` file, and SQLite refuses it even if a ``INSERT`` were attempted. It *can*
still map the ``-shm`` sidecar of a WAL-mode database for concurrent readers, because
that shared-memory index belongs to the WAL protocol rather than to this handle. So the
companion test asserts the database bytes and mtime are untouched, not that the
directory has no activity whatsoever — that is the promise this tool can actually keep.

Usage::

    python3 -S Fast_Fetch/audit_staging.py            # human-readable table
    python3 -S Fast_Fetch/audit_staging.py --json     # machine-readable
    python3 -S Fast_Fetch/audit_staging.py --data-dir /tmp/dbs --all
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

try:  # config resolves the fleet data directory (RADD_DATA_DIR, else the Oracle path).
    from config import DATA_DIR as DEFAULT_DATA_DIR
except Exception:  # pragma: no cover - a broken brand file must not make the audit fatal
    DEFAULT_DATA_DIR = Path.cwd()

# The files that are not a single-site staging catalog: the merged output, the live
# production catalog, snapshots, and the non-catalog stores. Each is skipped with a
# reason so ``--all`` can still show the whole directory honestly.
SKIP_PREFIXES = ("merged_catalog",)
SKIP_NAMES = ("fast_fetch.db", "user_state.db", "resolvers.db")
SKIP_SUBSTRINGS = ("_backup",)

SOURCE_FALLBACK_TABLES = ("download_sources", "post_sources")

# raw_meta is a scraped JSON blob that can run to kilobytes per row across catalogs of
# a few hundred thousand posts, so the key census is a bounded sample, clearly labelled
# as one in the output rather than presented as a full-table fact.
DEFAULT_RAW_META_SAMPLE = 500


def skip_reason(name: str) -> str | None:
    """Why this file is not a per-site staging catalog, or None if it should be audited."""
    lower = name.lower()
    if not lower.endswith(".db"):
        return "not a database"
    if any(lower.startswith(prefix) for prefix in SKIP_PREFIXES):
        return "merged catalog"
    if lower in SKIP_NAMES:
        return "not a staging catalog"
    if any(token in lower for token in SKIP_SUBSTRINGS):
        return "backup snapshot"
    return None


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in conn.execute("PRAGMA table_info(%s)" % table)]


def _count(conn: sqlite3.Connection, table: str) -> int:
    return conn.execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0]


def _grouped(conn: sqlite3.Connection, table: str, column: str, limit: int = 25) -> dict:
    """Value -> row count for one column, with NULL collected as the key ``(null)``."""
    rows = conn.execute(
        "SELECT COALESCE(CAST(%s AS TEXT), '(null)') AS k, COUNT(*) FROM %s GROUP BY k ORDER BY 2 DESC LIMIT %d"
        % (column, table, limit)
    ).fetchall()
    return {str(key): int(count) for key, count in rows}


def audit_database(path: Path, raw_meta_sample: int = DEFAULT_RAW_META_SAMPLE) -> dict:
    """Everything this tool can honestly say about one staging database, read-only."""
    report = {
        "database": path.name,
        "path": str(path),
        "bytes": None,
        "modified": None,
        "tables": [],
        "counts": {"posts": 0, "releases": 0, "sources": 0},
        "fallback_source_rows": {},
        "subtitle_source_rows": None,
        "playback_types": None,
        "media_types": None,
        "raw_meta": None,
        "adult_column_present": False,
        "adult_posts": None,
        "source_health": None,
        "warnings": [],
    }

    # Statted defensively: a caller can hand us a name that is not there, and the answer
    # to that is a warning, never a traceback out of an inventory tool.
    try:
        stat = path.stat()
        report["bytes"] = stat.st_size
        report["modified"] = datetime.fromtimestamp(stat.st_mtime, timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    except OSError as error:
        report["warnings"].append("cannot stat: %s" % error)
        return report

    try:
        conn = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    except sqlite3.Error as error:
        report["warnings"].append("cannot open read-only: %s" % error)
        return report

    try:
        try:  # A frozen-but-locked catalog should be waited for, not failed on.
            conn.set_busy_timeout(5000)
        except AttributeError:  # Python < 3.10 has no setter.
            pass

        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        report["tables"] = sorted(tables)

        for table, key in (("posts", "posts"), ("releases", "releases"), ("sources", "sources")):
            if table in tables:
                report["counts"][key] = _count(conn, table)

        if "sources" not in tables:
            held = {t: _count(conn, t) for t in SOURCE_FALLBACK_TABLES if t in tables}
            report["fallback_source_rows"] = held
            if held:
                report["warnings"].append(
                    "no sources table; legacy link tables hold %s"
                    % ", ".join("%s=%d" % item for item in sorted(held.items()))
                )
            else:
                report["warnings"].append("no sources table and no legacy link table")
        else:
            source_columns = _columns(conn, "sources")
            if "playback_type" in source_columns:
                report["playback_types"] = _grouped(conn, "sources", "playback_type")
                report["subtitle_source_rows"] = int(
                    report["playback_types"].get("subtitle", 0)
                )
            else:
                report["warnings"].append("sources has no playback_type; subtitle coverage is unmeasurable")
            if "status" in source_columns:
                report["source_health"] = _grouped(conn, "sources", "status")
            else:
                report["warnings"].append("sources has no status column; no link-health breakdown")

        if "posts" not in tables:
            report["warnings"].append("posts table absent")
        else:
            post_columns = _columns(conn, "posts")
            report["adult_column_present"] = "is_18_plus" in post_columns
            if report["adult_column_present"]:
                report["adult_posts"] = conn.execute(
                    "SELECT COUNT(*) FROM posts WHERE is_18_plus=1"
                ).fetchone()[0]
            else:
                report["warnings"].append("posts has no is_18_plus; adult coverage is unauditable")

            if "media_type" in post_columns:
                report["media_types"] = _grouped(conn, "posts", "media_type")

            if "raw_meta" in post_columns and raw_meta_sample > 0:
                report["raw_meta"] = _raw_meta_census(conn, raw_meta_sample)

        for table in ("posts", "releases", "sources"):
            if table in tables and report["counts"][table] == 0:
                report["warnings"].append("%s is empty" % table)
    finally:
        conn.close()

    return report


def _raw_meta_census(conn: sqlite3.Connection, sample: int) -> dict:
    """What the scraped JSON blob actually carries, over a bounded sample of posts.

    The point is the subtitle signal that ``playback_type`` does not cover: an importer
    that captured a ``subtitles`` entry but never made it a source row shows up here as
    a count, which is what tells the operator whether coverage is missing or unmeasured.
    """
    census = {
        "sampled": 0,
        "parsed": 0,
        "unparsed": 0,
        "keys": {},
        "posts_with_subtitles": 0,
        "subtitle_types": {},
    }
    rows = conn.execute(
        "SELECT raw_meta FROM posts WHERE raw_meta IS NOT NULL AND raw_meta != '' LIMIT %d"
        % sample
    ).fetchall()
    for (raw,) in rows:
        census["sampled"] += 1
        try:
            blob = json.loads(raw)
        except (ValueError, TypeError):
            census["unparsed"] += 1
            continue
        if not isinstance(blob, dict):
            census["unparsed"] += 1
            continue
        census["parsed"] += 1
        for key in blob:
            census["keys"][key] = census["keys"].get(key, 0) + 1
        subtitles = blob.get("subtitles")
        entries = subtitles if isinstance(subtitles, list) else ([subtitles] if subtitles else [])
        if entries:
            census["posts_with_subtitles"] += 1
            for entry in entries:
                if isinstance(entry, dict):
                    kind = str(entry.get("kind") or entry.get("language") or entry.get("name") or "(unnamed)")
                else:
                    kind = str(entry)
                census["subtitle_types"][kind] = census["subtitle_types"].get(kind, 0) + 1
    return census


def audit_directory(data_dir: Path, raw_meta_sample: int = DEFAULT_RAW_META_SAMPLE, include_skipped: bool = False) -> dict:
    """Audit every per-site staging catalog in one directory."""
    result = {"data_dir": str(data_dir), "audited": [], "skipped": [], "totals": {}, "warnings": []}
    if not data_dir.is_dir():
        result["warnings"].append("data directory does not exist")
        return result

    for path in sorted(data_dir.glob("*.db")):
        reason = skip_reason(path.name)
        if reason:
            if include_skipped:
                result["skipped"].append({"database": path.name, "reason": reason, "bytes": path.stat().st_size})
            continue
        result["audited"].append(audit_database(path, raw_meta_sample))

    totals = {
        "databases": len(result["audited"]),
        "posts": sum(item["counts"]["posts"] for item in result["audited"]),
        "releases": sum(item["counts"]["releases"] for item in result["audited"]),
        "sources": sum(item["counts"]["sources"] for item in result["audited"]),
        "subtitle_sources": sum(
            item["subtitle_source_rows"] or 0 for item in result["audited"]
        ),
        "adult_posts": sum(item["adult_posts"] or 0 for item in result["audited"]),
        "databases_with_schema_warnings": sum(1 for item in result["audited"] if item["warnings"]),
    }
    result["totals"] = totals
    return result


def _format_number(value) -> str:
    if value is None:
        return "n/a"
    return f"{value:,}" if isinstance(value, int) else str(value)


def _compact(mapping, limit: int = 4) -> str:
    """``{'active': 19, 'unknown': 21}`` -> ``active 19, unknown 21, +1 more``."""
    if not mapping:
        return "-"
    items = sorted(mapping.items(), key=lambda pair: -pair[1])
    shown = ", ".join(f"{key} {value:,}" for key, value in items[:limit])
    if len(items) > limit:
        shown += f", +{len(items) - limit} more"
    return shown


def render_table(result: dict) -> str:
    lines = []
    header = (
        f"{'DATABASE':<30}{'POSTS':>10}{'RELEASES':>10}{'SOURCES':>10}"
        f"{'SUBTITLE':>10}{'ADULT':>8}  SOURCE STATUS / MEDIA TYPE"
    )
    lines.append(header)
    lines.append("-" * len(header))
    for item in result["audited"]:
        subtitle = "n/a" if item["subtitle_source_rows"] is None else _format_number(item["subtitle_source_rows"])
        health_bits = []
        if item["source_health"]:
            health_bits.append("status: " + _compact(item["source_health"], 3))
        if item["media_types"]:
            health_bits.append("media: " + _compact(item["media_types"], 3))
        if item["raw_meta"] and item["raw_meta"]["posts_with_subtitles"]:
            health_bits.append(
                "raw_meta subtitles: %d/%d sampled"
                % (item["raw_meta"]["posts_with_subtitles"], item["raw_meta"]["sampled"])
            )
        detail = " | ".join(health_bits) or "-"
        lines.append(
            f"{item['database']:<30}{_format_number(item['counts']['posts']):>10}"
            f"{_format_number(item['counts']['releases']):>10}"
            f"{_format_number(item['counts']['sources']):>10}{subtitle:>10}"
            f"{_format_number(item['adult_posts']):>8}  {detail}"
        )
        if item["warnings"]:
            for warning in item["warnings"]:
                lines.append(f"{'':<30}! {warning}")

    totals = result["totals"]
    if totals:
        lines.append("-" * len(header))
        lines.append(
            f"{'TOTAL (' + str(totals['databases']) + ' catalogs)':<30}{_format_number(totals['posts']):>10}"
            f"{_format_number(totals['releases']):>10}{_format_number(totals['sources']):>10}"
            f"{_format_number(totals['subtitle_sources']):>10}{_format_number(totals['adult_posts']):>8}"
        )
    if result["skipped"]:
        lines.append("")
        lines.append("Skipped: " + ", ".join(f"{item['database']} ({item['reason']})" for item in result["skipped"]))
    for warning in result["warnings"]:
        lines.append("! " + warning)
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Read-only inventory of the staging catalogs.")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR), help="directory holding <site>.db files")
    parser.add_argument("--json", action="store_true", help="emit the full report as JSON")
    parser.add_argument("--all", action="store_true", help="also list the files this tool skips, and why")
    parser.add_argument(
        "--raw-meta-sample",
        type=int,
        default=DEFAULT_RAW_META_SAMPLE,
        help="posts whose raw_meta JSON is parsed per catalog (0 disables)",
    )
    args = parser.parse_args(argv)

    result = audit_directory(Path(args.data_dir), args.raw_meta_sample, args.all)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(render_table(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
