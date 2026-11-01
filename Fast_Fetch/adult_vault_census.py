#!/usr/bin/env python3
"""#37's census, as a command instead of as a plan.

The 08xx pricing pass (`checkpoints/20261101-08xx-...-vault-pricing-...md`) answered the question
"is there a cheap way to count the adult flag across the last 19 staging vaults": **no**. No vault
indexes `is_18_plus`, so `SELECT COUNT(*) FROM posts WHERE is_18_plus=1` plans `SCAN posts` in 19 of
19, and the collision query walks a `canonical_key` index in 16 and an autoindex in 3. What that pass
left behind was a table of numbers and no way to execute them — which is how a window gets spent
re-deriving an order, three times over. This file is the plan turned into a program.

It counts two things per vault, and nothing else:

* `flagged` — rows carrying the site's adult flag;
* `keys_both` — `canonical_key` values holding **both** a flagged and an unflagged row. That is the
  exposure shape the root invariant worries about: a work hidden by one row and served by its twin.
  A key holding only flagged rows is correctly hidden and is *not* an exposure, `NULL` keys are never
  twins of each other, and `''`/`unknown` are the shared bucket every titleless payload lands in —
  all three rules are inherited from `test_adult_twin_probe.py` and `audit_adult_flags.py`, not
  reinvented here.

The four things that make it safe to start in a window:

1. **`mode=ro`, always.** Not "we promise not to write": a read-only URI refuses an UPDATE even if the
   code below is wrong, and it cannot checkpoint a WAL someone else owns.
2. **It re-stats each vault after counting it and refuses to continue if the file moved.** A census
   that changed its own input is not a census, and a size+mtime pair edited under q3's merge guard is
   how one lane's measurement invalidates another's safety check. Same for a `-wal`/`-shm`/`-journal`
   sibling appearing next to a vault.
3. **A budget it cannot overrun silently.** Costs are projected per vault from the measured
   0.9-5.0 s/MB spread on this box; when the remaining budget cannot cover the cheapest thing left,
   the run stops, prints what it did *not* count, and marks the result incomplete. A partial census
   that reads as a full one is worse than no census.
4. **Tier order by measurement, not impatience.** The tiers are the cost bands the 08xx pass published
   and this file reproduces exactly: A 300,912,640 B (4 sites, 5-25 CPU-minutes), B 883,949,568 B (6
   sites, 13-74 more), C 3,420,188,672 B (9 sites, 51-285 more). `world4ufree` + `9xmovies` are 30% of
   the corpus on their own; a run that starts in tier C looks like a failure while it is going fine.

Generational pairs are counted **once**. `katmoviehd.db`/`katmoviehd_refreshed.db` and
`multimovies.db`/`multimovies_full_20261022.db` are almost certainly the same corpus at two
generations; the redundant member is 561 MB = 12% of the budget spent to measure one site twice. By
default the runner counts the member named in `LINEAGE`'s value and reports the other as a lineage
row without summing it. Which member is really the merge input is q3's call, so
`--include-lineage` counts both and prints the pair as two rows.

Nothing here is read at import time, and that is deliberate: `config.py` asks a directory for
`Path.exists()`, `exists()` re-raises EACCES, and a CI worker that cannot stat `/home/ubuntu` ends the
job before its first assertion (measured by q5 at `eb4c0ee`). `config` is therefore imported inside
`main()` only, so `test_adult_vault_census.py` can exercise the plan offline.

    python3 -S Fast_Fetch/adult_vault_census.py --list                     # the plan, no file opened
    python3 -S Fast_Fetch/adult_vault_census.py --tier A --budget 1800      # 4 sites, one admitted window
    python3 -S Fast_Fetch/adult_vault_census.py --tier ABC --budget 21600   # the whole remainder

Stdlib only. Read-only. Never run it while the merge is reading the same vaults.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
import urllib.parse
from pathlib import Path

#: Measured 2026-11-01 08:xx with `stat -c %s`, decimal bytes; tier as published by the 08xx plan.
#: `rogmovies.db` was priced in that pass and *named* in its table but missing from its tier rows —
#: its 157,319,168 B were already inside tier C's published 3.42 GB, so the cost figures were right
#: and only the membership line was incomplete. Sum: 4,605,050,880 B, asserted against the published
#: total and against A/B/C = 300,912,640 / 883,949,568 / 3,420,188,672 by the test module.
PRICED = {
    "hindilinks4u.db": (62_148_608, "A"),
    "filmyhit.db": (70_627_328, "A"),
    "kisskh.db": (78_135_296, "A"),
    "7starhd.db": (90_001_408, "A"),
    "hdhub4u.db": (122_228_736, "B"),
    "katmoviehd.db": (125_546_496, "B"),
    "rareanimes.db": (125_554_688, "B"),
    "katmoviehd_refreshed.db": (125_571_072, "B"),
    "rogmovies.db": (157_319_168, "C"),
    "moviesmela.db": (183_685_120, "B"),
    "toonworld4all.db": (201_363_456, "B"),
    "ssrmovies.db": (284_966_912, "C"),
    "10xflix.db": (212_877_312, "C"),
    "bolly4u.db": (225_685_504, "C"),
    "multimovies.db": (349_741_056, "C"),
    "vegamovies.db": (364_945_408, "C"),
    "multimovies_full_20261022.db": (435_691_520, "C"),
    "9xmovies.db": (548_896_768, "C"),
    "world4ufree.db": (840_065_024, "C"),
}

TIERS = ("A", "B", "C")

#: redundant member -> the member the census counts. This is a *proposal*, not a fact: `katmoviehd
#: _refreshed` is the later generation of `katmoviehd`, and the dated `multimovies_full_20261022` is a
#: snapshot of the still-named `multimovies`. Which member of each pair is actually a merge input is
#: q3's decision, so `--include-lineage` counts both and prints each as its own row rather than the
#: runner pretending to know. The saving this line claims is 561,262,592 B = 12.2% of the corpus.
LINEAGE = {
    "katmoviehd_refreshed.db": "katmoviehd.db",
    "multimovies_full_20261022.db": "multimovies.db",
}

#: The measured per-MB spread of the same two statements on this box (05xx census: `pagalmovies`
#: 44.9 MB in 38.3 s, `filmyzilla` 33.7 MB in 153.8 s). Used to project, never to claim a measurement.
SECONDS_PER_MB = (0.9, 5.0)

#: Never census targets. `merged_catalog_*` is a production read, `user_state.db` is q3's credential
#: store, `fast_fetch.db` is a symlink to the live catalog. Naming them here means a mistyped
#: `--only` cannot reach them.
FORBIDDEN = frozenset({
    "merged_catalog_20261025.db", "fast_fetch.db", "user_state.db", "resolvers.db",
})

FLAG_COLUMN_CANDIDATES = ("is_18_plus", "is_adult")

#: Everything this file knows the name of: priced vaults plus the forbidden set. Anything else on
#: disk is reported as unpriced rather than quietly censused or quietly ignored.
priced_names = set(PRICED) | FORBIDDEN

FLAG_COUNT = "SELECT COUNT(*) FROM posts WHERE {flag} = 1"
TOTAL_ROWS = "SELECT COUNT(*) FROM posts"
KEY_COLLISION = (
    "SELECT COUNT(*), SUM(flagged), SUM(clean) FROM ("
    "  SELECT canonical_key,"
    "         SUM(CASE WHEN COALESCE({flag}, 0) = 1 THEN 1 ELSE 0 END) AS flagged,"
    "         SUM(CASE WHEN COALESCE({flag}, 0) = 0 THEN 1 ELSE 0 END) AS clean"
    "  FROM posts"
    "  WHERE canonical_key IS NOT NULL AND canonical_key <> '' AND canonical_key <> 'unknown'"
    "  GROUP BY canonical_key"
    "  HAVING flagged > 0 AND clean > 0)"
)


def project_cost(nbytes: int) -> tuple[float, float]:
    """Projected seconds for one vault, from the measured s/MB spread. A projection, not a promise."""
    mb = nbytes / 1e6
    return (mb * SECONDS_PER_MB[0], mb * SECONDS_PER_MB[1])


def tier_bytes(tier: str) -> int:
    return sum(size for size, name in PRICED.values() if name == tier)


def plan(tiers: str = "ABC", *, include_lineage: bool = False,
         only: str | None = None) -> list[dict]:
    """The ordered census plan: tier A first, cheapest vault in each tier first.

    Pure arithmetic over `PRICED` — no path is opened, no directory is listed — so a window can be
    spent counting and not deciding.
    """
    wanted = set(tiers.upper())
    redundant = set() if include_lineage else set(LINEAGE)
    rows = []
    for name, (size, tier) in sorted(PRICED.items(), key=lambda kv: (kv[1][1], kv[1][0])):
        if tier not in wanted or (only and name != only):
            continue
        lo, hi = project_cost(size)
        counted = name not in redundant
        rows.append({"vault": name, "tier": tier, "bytes": size,
                     "seconds": (round(lo, 1), round(hi, 1)), "counted": counted,
                     "lineage_of": LINEAGE.get(name)})
    if only:
        return rows
    return [r for r in rows if r["counted"]] + [r for r in rows if not r["counted"]]


def open_readonly(path: Path) -> sqlite3.Connection:
    """`mode=ro` is the whole write guarantee, so it is built here and nowhere else."""
    uri = "file:" + urllib.parse.quote(Path(path).resolve().as_posix()) + "?mode=ro"
    return sqlite3.connect(uri, uri=True)


def flag_column(conn) -> str | None:
    have = {row[1] for row in conn.execute("PRAGMA table_info(posts)")}
    if not have:
        return None
    return next((name for name in FLAG_COLUMN_CANDIDATES if name in have), None)


def fingerprint(path: Path) -> tuple[int, int]:
    stat = Path(path).stat()
    return (stat.st_size, stat.st_mtime_ns)


def assert_untouched(path: Path, before: tuple[int, int]) -> None:
    """Prove the census did not modify or co-write its own input.

    Split out of `census_vault` so a test can drive it with a file that really did move, instead of
    trusting that a read-only open is enough.
    """
    after = fingerprint(path)
    if after != before:
        raise CensusRefused(f"{path.name} CHANGED during the census: size/mtime "
                            f"{before} -> {after}. Stop; something is writing a census input.")
    sidecars = stray_sidecars(path)
    if sidecars:
        raise CensusRefused(f"{path.name} grew {sidecars} during the census — a read-only open "
                            f"cannot do that, so this process is not the only writer.")


def stray_sidecars(path: Path) -> list[str]:
    """A `-wal`/`-shm`/`-journal` that appears beside a vault means something opened it writable."""
    base = str(path)
    return [suffix for suffix in ("-wal", "-shm", "-journal")
            if Path(base + suffix).exists()]


class CensusRefused(RuntimeError):
    """The census stopped because continuing would cost more than it is allowed to."""


def census_vault(path: Path) -> dict:
    """Count one vault, and prove the counting did not touch it."""
    if Path(path).name in FORBIDDEN:
        raise CensusRefused(f"{path.name} is not a census target")
    before = fingerprint(path)
    started = time.monotonic()
    conn = open_readonly(path)
    try:
        flag = flag_column(conn)
        if flag is None:
            raise CensusRefused(f"{path.name}: no `posts.is_18_plus`/`is_adult` column to count")
        total = int(conn.execute(TOTAL_ROWS).fetchone()[0] or 0)
        flagged = int(conn.execute(FLAG_COUNT.format(flag=flag)).fetchone()[0] or 0)
        row = conn.execute(KEY_COLLISION.format(flag=flag)).fetchone()
        exposed_flagged = int(row[1] or 0)
        exposed_clean = int(row[2] or 0)
    finally:
        conn.close()
    elapsed = time.monotonic() - started
    assert_untouched(path, before)
    return {"vault": path.name, "flag_column": flag, "rows": total, "flagged": flagged,
            "keys_both": int(row[0] or 0), "rows_on_exposed_keys": exposed_flagged + exposed_clean,
            "flagged_rows_on_exposed_keys": exposed_flagged,
            "seconds": round(elapsed, 2)}


def run(data_dir: Path, tiers: str = "ABC", *, include_lineage: bool = False,
        only: str | None = None, budget: float | None = None) -> dict:
    """Walk the plan until the budget or the vaults run out. Read-only, and it says so in the result."""
    if only is not None and only not in PRICED:
        raise CensusRefused(
            "%s is not in the priced census set (%s)"
            % (only, "it is a forbidden target" if only in FORBIDDEN else "never sized on 2026-11-01"))
    targets = plan(tiers, include_lineage=include_lineage, only=only)
    if not targets:
        raise CensusRefused("the plan is empty — nothing would be counted, so nothing is claimed")
    out = {"data_dir": str(data_dir), "results": [], "skipped": [],
           "unpriced_on_disk": [], "complete": False, "elapsed": 0.0}
    #: A vault another lane added after the 08xx pricing is not silently ignored: it is reported, so
    #: the census's own coverage claim stays checkable by whoever reads the number. `*_readonly.db`
    #: snapshots are excluded because they are copies of a priced file, not a new site.
    disk = {p.name for p in Path(data_dir).glob("*.db")
            if not p.name.endswith("_readonly.db")}
    out["unpriced_on_disk"] = sorted(disk - priced_names)
    started = time.monotonic()
    for index, target in enumerate(targets):
        path = Path(data_dir) / target["vault"]
        if not target["counted"]:
            out["skipped"].append({"vault": target["vault"], "reason": "lineage of %s"
                                   % target["lineage_of"], "bytes": target["bytes"]})
            continue
        if not path.exists():
            out["skipped"].append({"vault": target["vault"], "reason": "not on disk",
                                   "bytes": target["bytes"]})
            continue
        spent = time.monotonic() - started
        if budget is not None:
            remaining = budget - spent
            if remaining < target["seconds"][0]:
                out["skipped"].extend({"vault": t["vault"], "reason": "over budget",
                                       "bytes": t["bytes"]}
                                      for t in targets[index:] if t["counted"] and t["bytes"])
                break
        try:
            result = census_vault(path)
        except (CensusRefused, sqlite3.Error) as exc:
            print(f"[!] {target['vault']}: {exc}", file=sys.stderr)
            out["refused"] = str(exc)
            break
        #: A staging vault is written by scrapers between pricing and census, so a size delta is
        #: normal — but it is exactly the number that decides whether the projected cost was honest.
        #: Reported per vault rather than refused, so a stale plan is visible to whoever reads it.
        result["size_delta_vs_pricing"] = path.stat().st_size - target["bytes"]
        result["tier"] = target["tier"]
        out["results"].append(result)
        print("%-30s tier %s %7.1f MB  rows %9d  flagged %7d  keys_both %6d  %5.1fs  delta %+d"
              % (result["vault"], target["tier"], target["bytes"] / 1e6, result["rows"],
                 result["flagged"], result["keys_both"], result["seconds"],
                 result["size_delta_vs_pricing"]), flush=True)
    out["elapsed"] = round(time.monotonic() - started, 1)
    counted = {r["vault"] for r in out["results"]}
    out["complete"] = bool(out["results"]) and not out["skipped"] and not out.get("refused") \
        and counted == {t["vault"] for t in targets if t["counted"]}
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tier", default="ABC", help="tiers to walk, in order (default ABC)")
    parser.add_argument("--only", default=None, help="census exactly this vault name")
    parser.add_argument("--budget", type=float, default=None,
                        help="wall-clock seconds this run may spend; it stops and reports the rest")
    parser.add_argument("--include-lineage", action="store_true",
                        help="count both members of a generational pair (costs 561 MB more)")
    parser.add_argument("--list", action="store_true",
                        help="print the plan and exit without opening a single file")
    parser.add_argument("--data-dir", default=None,
                        help="staging dir (default: config.DATA_DIR, resolved at run time)")
    args = parser.parse_args(argv)

    if args.list:
        rows = plan(args.tier, include_lineage=args.include_lineage, only=args.only)
        for row in rows:
            print("%-30s tier %s %7.1f MB  %5.1f-%5.1f s  %s"
                  % (row["vault"], row["tier"], row["bytes"] / 1e6, row["seconds"][0],
                     row["seconds"][1],
                     "LINEAGE of %s — not counted" % row["lineage_of"] if not row["counted"]
                     else "count"))
        counted_bytes = sum(r["bytes"] for r in rows if r["counted"])
        print("\n%d counted, %d lineage, %.2f GB to walk, projected %.0f-%.0f s"
              % (sum(1 for r in rows if r["counted"]), sum(1 for r in rows if not r["counted"]),
                 counted_bytes / 1e9,
                 counted_bytes / 1e6 * SECONDS_PER_MB[0],
                 counted_bytes / 1e6 * SECONDS_PER_MB[1]))
        return 0

    if args.data_dir:
        data_dir = Path(args.data_dir)
    else:
        import config                                  # lazily, on purpose — see the docstring
        data_dir = Path(config.DATA_DIR)
    print(f"[i] census target dir: {data_dir}  (read-only; nothing here is written)")
    try:
        result = run(data_dir, args.tier, include_lineage=args.include_lineage,
                     only=args.only, budget=args.budget)
    except CensusRefused as exc:
        print(f"[!] refusing to run: {exc}", file=sys.stderr)
        return 2
    print("RESULT\t" + json.dumps(result, sort_keys=True))
    if not result["complete"]:
        print("[!] INCOMPLETE: %d counted, %d skipped, refused=%s"
              % (len(result["results"]), len(result["skipped"]), result.get("refused")),
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
