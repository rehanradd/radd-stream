#!/usr/bin/env python3
"""
restamp_provenance.py — repair the source_site provenance defects D1/D3 wrote.

Two historical mistakes are repaired here:
  D3  hdtvb pages that the copy-pasted importer stamped `hdhub4u`.
  D1  desicinemas pages written by a posts table that had no site column at all,
      which merge_catalogs therefore carried as `unknown`.

A row's real site is decided from evidence, never guessed:
  * URL evidence — the exact page URL is present in that site's own staging DB.
  * Host evidence — domain_registry.json assigns the page URL's host to a site.
A row already stamped with some site is only re-stamped when BOTH kinds of
evidence agree on the same different site (that is the D3 shape). A row stamped
`unknown` (the D1 shape) is given the site any single evidence source proves.

DRY RUN BY DEFAULT: nothing is written unless --apply is passed, and --apply
takes a consistent backup copy of the database first. A path naming the
production catalog is refused outright unless --force-production is also passed.

Usage:
    python3 -S Fast_Fetch/restamp_provenance.py --db /home/ubuntu/radd-stream-data/merged_catalog.db
    python3 -S Fast_Fetch/restamp_provenance.py --db <staging.db> --apply
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
import urllib.parse
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# The live unified catalog. This tool must never touch it by accident, so the
# name is refused unless the operator passes --force-production.
try:  # prefer the brand-derived name when config is importable
    from config import DB_PATH as _CONFIG_DB_PATH

    PRODUCTION_DB_NAME = Path(_CONFIG_DB_PATH).name
except Exception:  # pragma: no cover - config import can fail on a bare checkout
    PRODUCTION_DB_NAME = "fast_fetch.db"

DEFAULT_STAGING_DIR = Path("/home/ubuntu/radd-stream-data")
DEFAULT_REGISTRY = BASE_DIR / "domain_registry.json"

# Values that mean "we lost the attribution", not "this is the site".
UNKNOWN_STAMPS = {"", "unknown", "none", "null", "n/a"}

# The only content types the catalog stores (fast_fetch.parse_post_metadata).
LEGAL_MEDIA_TYPES = ("movie", "series", "complete_season", "ongoing_season")

# table -> (page-url columns, site columns). Only page URLs are consulted: a
# release's mirror URL says nothing about which site the page came from, so
# sources/download_sources are deliberately out of scope.
PROVENANCE_TABLES = {
    "posts": (["url", "post_url", "loc"], ["source_site", "site"]),
    "releases": (["origin_url"], ["source_site", "site"]),
    "post_sources": (["url"], ["source_site", "site"]),
}
MEDIA_TYPE_COLUMNS = ["content_type", "media_type"]


def normalize_site_key(value) -> str:
    return "".join(c for c in str(value or "").casefold() if c.isalnum())


def host_of(url) -> str:
    host = urllib.parse.urlsplit(str(url or "")).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def _first_present(columns: list[str], candidates: list[str]) -> str | None:
    for name in candidates:
        if name in columns:
            return name
    return None


def load_host_map(registry_path: Path) -> dict[str, str]:
    """host -> site, from every site's active base URL and known mirrors."""
    if not Path(registry_path).exists():
        return {}
    data = json.loads(Path(registry_path).read_text(encoding="utf-8"))
    host_map: dict[str, str] = {}
    for site, entry in (data.get("sites") or {}).items():
        for raw in [entry.get("active_base_url")] + list(entry.get("known_mirrors") or []):
            host = host_of(raw)
            if host:
                host_map.setdefault(host, site)
    return host_map


def collect_url_evidence(staging_dir: Path, site_keys: set[str], skip_paths: set[Path]) -> dict[str, str]:
    """exact page URL -> site, proven by that site's own staging database holding it."""
    evidence: dict[str, str] = {}
    staging_dir = Path(staging_dir)
    if not staging_dir.is_dir():
        return evidence
    known = {normalize_site_key(k) for k in site_keys}
    for db_file in sorted(staging_dir.glob("*.db")):
        site = normalize_site_key(db_file.stem)
        if site not in known:
            continue  # merged / production / backup catalogs are not origin evidence
        resolved = db_file.resolve()
        if resolved in skip_paths or PRODUCTION_DB_NAME in db_file.name:
            continue
        try:
            conn = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True)
        except sqlite3.Error:
            continue
        try:
            conn.execute("PRAGMA busy_timeout = 10000")
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for table in ("sitemap_cache", "posts"):
                if table not in tables:
                    continue
                col = _first_present(table_columns(conn, table), ["loc", "url", "post_url"])
                if not col:
                    continue
                for (url,) in conn.execute(f"SELECT {col} FROM {table} WHERE {col} IS NOT NULL"):
                    text = str(url).strip()
                    if text:
                        evidence.setdefault(text, site)
        except sqlite3.Error:
            pass
        finally:
            conn.close()
    return evidence


def target_site_for(current: str, url, url_evidence: dict[str, str], host_map: dict[str, str]) -> str | None:
    """The site this row should carry, or None when it must be left alone."""
    current_key = str(current or "").strip().lower()
    evidence_site = url_evidence.get(str(url or "").strip())
    host_site = host_map.get(host_of(url))
    if current_key in UNKNOWN_STAMPS:
        return evidence_site or host_site
    if evidence_site and host_site and evidence_site == host_site and evidence_site != current_key:
        return evidence_site
    return None


def normalize_media_type(value) -> str:
    """Clamp a stored page type onto the catalog's four legal content types."""
    text = str(value or "movie").strip().lower()
    if text in LEGAL_MEDIA_TYPES:
        return text
    if any(token in text for token in ("episode", "season", "series", "batch", "pack")):
        return "series"
    return "movie"


class Plan:
    """A computed, not-yet-applied set of repairs."""

    def __init__(self) -> None:
        self.site_changes: dict[tuple, int] = {}
        self.media_changes: dict[tuple, int] = {}
        self.site_before: dict[tuple, int] = {}
        self.site_after: dict[tuple, int] = {}
        self.unresolved: dict[tuple, int] = {}
        self.site_updates: list[tuple] = []
        self.media_updates: list[tuple] = []

    @property
    def site_rows(self) -> int:
        return len(self.site_updates)

    @property
    def media_rows(self) -> int:
        return len(self.media_updates)

    @property
    def total_rows(self) -> int:
        return len(self.site_updates) + len(self.media_updates)


def build_plan(conn: sqlite3.Connection, url_evidence: dict[str, str], host_map: dict[str, str],
               *, fix_media_types: bool = True) -> Plan:
    """Read-only pass that decides every row the repair would change."""
    plan = Plan()
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    for table, (url_candidates, site_candidates) in PROVENANCE_TABLES.items():
        if table not in tables:
            continue
        columns = table_columns(conn, table)
        site_col = _first_present(columns, site_candidates)
        url_col = _first_present(columns, url_candidates)
        if not site_col or not url_col:
            continue
        for row_id, current, url in conn.execute(
            f"SELECT rowid, {site_col}, {url_col} FROM {table}"
        ).fetchall():
            current_text = str(current or "").strip()
            stamp_key = (table, site_col, current_text or "(empty)")
            plan.site_before[stamp_key] = plan.site_before.get(stamp_key, 0) + 1
            proposed = target_site_for(current_text, url, url_evidence, host_map)
            new_site = proposed or current_text
            after_key = (table, site_col, new_site or "(empty)")
            plan.site_after[after_key] = plan.site_after.get(after_key, 0) + 1
            if new_site == current_text:
                if current_text.lower() in UNKNOWN_STAMPS:
                    plan.unresolved[(table, site_col)] = plan.unresolved.get((table, site_col), 0) + 1
                continue
            change_key = (table, site_col, current_text or "(empty)", new_site)
            plan.site_changes[change_key] = plan.site_changes.get(change_key, 0) + 1
            plan.site_updates.append((table, site_col, row_id, new_site))

    if fix_media_types and "posts" in tables:
        media_col = _first_present(table_columns(conn, "posts"), MEDIA_TYPE_COLUMNS)
        if media_col:
            for row_id, value in conn.execute(f"SELECT rowid, {media_col} FROM posts").fetchall():
                current_text = str(value or "").strip()
                legal = normalize_media_type(current_text)
                if legal == current_text.lower():
                    continue
                change_key = ("posts", media_col, current_text or "(empty)", legal)
                plan.media_changes[change_key] = plan.media_changes.get(change_key, 0) + 1
                plan.media_updates.append(("posts", media_col, row_id, legal))
    return plan


def apply_plan(conn: sqlite3.Connection, plan: Plan) -> int:
    """Write the planned repairs in one transaction. Returns rows updated."""
    touched = 0
    with conn:
        for table, column, row_id, value in plan.site_updates + plan.media_updates:
            conn.execute(f"UPDATE {table} SET {column} = ? WHERE rowid = ?", (value, row_id))
            touched += 1
    return touched


def backup_database(db_path: Path) -> Path:
    """Consistent (WAL-safe) snapshot taken before the first write."""
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    target = Path(db_path).with_name(f"{Path(db_path).name}.pre-restamp-{stamp}.bak")
    src = sqlite3.connect(str(db_path))
    dst = sqlite3.connect(str(target))
    try:
        with dst:
            src.backup(dst)
    finally:
        src.close()
        dst.close()
    return target


def _print_rows(header: str, rows: list[tuple], columns: list[str]) -> None:
    print(f"\n{header}")
    if not rows:
        print("  (none)")
        return
    widths = [len(c) for c in columns]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))
    print("  " + "  ".join(str(c).ljust(widths[i]) for i, c in enumerate(columns)))
    print("  " + "  ".join("-" * w for w in widths))
    for row in rows:
        print("  " + "  ".join(str(cell).ljust(widths[i]) for i, cell in enumerate(row)))


def report(plan: Plan, *, applied: bool) -> None:
    print(f"\n=== {'RE-STAMP APPLIED' if applied else 'WOULD RE-STAMP (dry run - nothing written)'} ===")
    _print_rows(
        "source_site changes",
        [list(key) + [count] for key, count in sorted(plan.site_changes.items())],
        ["TABLE", "COLUMN", "BEFORE", "AFTER", "ROWS"],
    )
    _print_rows(
        "content_type / media_type normalization",
        [list(key) + [count] for key, count in sorted(plan.media_changes.items())],
        ["TABLE", "COLUMN", "BEFORE", "AFTER", "ROWS"],
    )

    sites = {key[2] for key in plan.site_before} | {key[2] for key in plan.site_after}
    totals = []
    for site in sorted(sites):
        before = sum(c for key, c in plan.site_before.items() if key[2] == site)
        after = sum(c for key, c in plan.site_after.items() if key[2] == site)
        totals.append((site, before, after, after - before))
    _print_rows("per-site totals across every provenance table", totals, ["SITE", "BEFORE", "AFTER", "DELTA"])

    print(f"\n  site rows changed : {plan.site_rows:,}")
    print(f"  media rows changed: {plan.media_rows:,}")
    for (table, column), count in sorted(plan.unresolved.items()):
        print(f"  [!] {count:,} rows in {table}.{column} carry no provable origin and stay unknown")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Dry-run-by-default provenance restamp for staging and unified SQLite catalogs.")
    parser.add_argument("--db", required=True, help="Target SQLite database (required; never defaults to production)")
    parser.add_argument("--apply", action="store_true", help="Write the repairs (default is a read-only dry run)")
    parser.add_argument("--force-production", action="store_true",
                        help=f"Allow a path naming the production catalog ({PRODUCTION_DB_NAME})")
    parser.add_argument("--staging-dir", default=str(DEFAULT_STAGING_DIR),
                        help="Directory of per-site staging databases used as origin evidence")
    parser.add_argument("--registry", default=str(DEFAULT_REGISTRY), help="domain_registry.json path")
    parser.add_argument("--no-media-type-fix", action="store_true", help="Skip content-type normalization")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    db_path = Path(args.db).expanduser().resolve()

    if not db_path.exists():
        print(f"[!] Database not found: {db_path}", file=sys.stderr)
        return 1

    if PRODUCTION_DB_NAME in db_path.name and not args.force_production:
        print(
            f"[!] REFUSED: {db_path} is the production catalog ({PRODUCTION_DB_NAME}).\n"
            "    Re-stamping it needs an explicit --force-production and owner sign-off.",
            file=sys.stderr,
        )
        return 2

    staging_dir = Path(args.staging_dir).expanduser()
    registry_path = Path(args.registry).expanduser()
    host_map = load_host_map(registry_path)
    url_evidence = collect_url_evidence(staging_dir, set(host_map.values()), {db_path})

    print(f"[*] Target      : {db_path}")
    print(f"[*] Mode        : {'APPLY' if args.apply else 'DRY RUN (read-only)'}")
    print(f"[*] Hosts       : {len(host_map):,} from {registry_path.name}")
    print(f"[*] URL evidence: {len(url_evidence):,} page URLs from {staging_dir}")

    mode = "rw" if args.apply else "ro"
    conn = sqlite3.connect(f"file:{db_path}?mode={mode}", uri=True)
    try:
        conn.execute("PRAGMA busy_timeout = 30000")
        plan = build_plan(conn, url_evidence, host_map, fix_media_types=not args.no_media_type_fix)
        if not args.apply:
            report(plan, applied=False)
            if plan.total_rows:
                print("\n[*] Re-run with --apply to write these repairs (a timestamped backup is taken first).")
            else:
                print("\n[OK] Nothing to repair - provenance already correct (idempotent).")
            return 0
        if plan.total_rows == 0:
            report(plan, applied=False)
            print("\n[OK] Nothing to repair - no backup taken (idempotent).")
            return 0
        backup = backup_database(db_path)
        print(f"\n[*] Backup written: {backup}")
        changed = apply_plan(conn, plan)
        report(plan, applied=True)
        print(f"\n[OK] Applied {changed:,} row updates to {db_path.name}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
