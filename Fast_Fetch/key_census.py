#!/usr/bin/env python3
"""Read-only census: how many stored rows the write-time key guard would re-file.

Task #13's second deliverable. `fast_fetch.guard_canonical_key` refuses to stamp a
`canonical_key` onto a row whose own title AND year contradict it; this reports what that
rule would have done to the rows already in a database, without touching a single row.

Why a census and not a migration: AGENTS.md and `backfill_adult_key.py`'s own docstring both
warn that re-keying stored rows is a reviewed migration of its own — 150k rows pushed onto a
title+year key sends thousands of works through `_find_existing_post`'s single-match rule and
breaks ingest. So the number this prints is an input to that decision, never an execution of it.

**The metric here is not the metric in `CROWN_KEY_CENSUS_13` §1, and the two are reported under
different names on purpose.** Crown's census counts a row as mis-keyed when its title alone fails
to name the key (164 keys, 19 of them flagged). This guard refuses only when the title AND the
year both fail, because year agreement is what makes *Kapatadhaari* / *Kabadadaari* — one film,
two spellings — fold instead of split. So `would_refuse` is a subset of `title_only_disagree`, and
a lane that quotes one as the other is wrong.

    python3 -S Fast_Fetch/key_census.py <db>            # the census
    python3 -S Fast_Fetch/key_census.py <db> --census --sample 40
    python3 -S Fast_Fetch/key_census.py <db> --json

Offline against a file you point at, opened `mode=ro` with `PRAGMA query_only`. No network, no
write, no re-key: `--apply` is accepted as an argument only so it can be refused out loud.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.resolve()))

import fast_fetch  # noqa: E402

REFUSAL_ORDER_13 = (
    "no production re-key in this task: the count is input to a reviewed migration "
    "(order #13 scope), not an execution of one"
)


def connect_read_only(db_path):
    """Open a catalog the way every read in this repository must: `mode=ro`, query_only."""
    path = Path(db_path).resolve()
    if not path.exists():
        raise SystemExit(f"no database at {path}")
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


def run_census(db_path, *, sample_limit=25) -> dict:
    conn = connect_read_only(db_path)
    try:
        report = fast_fetch.census_key_refusals(conn, sample_limit=sample_limit)
        report["db"] = str(Path(db_path).resolve())
        report["writable"] = False
        return report
    finally:
        conn.close()


def render(report) -> str:
    lines = [
        "key-refusal census (read-only; nothing was written)",
        "  database                     : %s" % report["db"],
        "  rows carrying a canonical_key: %d" % report["rows_with_key"],
        "  title fails to name its key  : %d   <- CROWN_KEY_CENSUS_13's metric"
        % report["title_only_disagree"],
        "  ...of which the guard refuses: %d   <- title AND year both fail"
        % report["would_refuse"],
        "  refused rows that are flagged: %d" % report["would_refuse_flagged"],
        "  title fails but year or no usable self-key keeps it: %d"
        % report["title_fails_but_year_or_no_self_key_carries_it"],
        "  distinct keys involved       : %d" % len(report["keys_affected"]),
    ]
    if report["samples"]:
        lines.append("  samples:")
        for row in report["samples"]:
            lines.append(
                "    id %-8s %-28s -> %-28s %s"
                % (row["id"], row["refused_key"], row["filed_under"],
                   "[flagged]" if row["flagged"] else "")
            )
    lines.append("")
    lines.append("  " + REFUSAL_ORDER_13)
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("db", type=Path, help="catalog to census (opened read-only)")
    parser.add_argument("--census", action="store_true",
                        help="the census report (the default; named so a caller states intent)")
    parser.add_argument("--sample", type=int, default=25,
                        help="how many refused rows to print (default 25)")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--apply", action="store_true",
                        help="refused: this tool cannot re-key a production catalog")
    args = parser.parse_args(argv)

    if args.apply:
        # Loud failure, not an ignored flag: someone reaching for --apply is about to make
        # a production write, and silence would let them believe the tool supports it.
        print("REFUSED: --apply is not implemented here. " + REFUSAL_ORDER_13,
              file=sys.stderr)
        return 2

    report = run_census(args.db, sample_limit=args.sample)
    print(json.dumps(report, indent=2, sort_keys=True) if args.json else render(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
