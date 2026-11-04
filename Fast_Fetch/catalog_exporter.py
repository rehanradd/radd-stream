#!/usr/bin/env python3
"""
Fast_Fetch/catalog_exporter.py — static JSON pre-generation for home/browse.
════════════════════════════════════════════════════════════════════════════
Backlog #3: render the browse surfaces to disk so a static file server can
answer them with zero request-path load. GATED by the Crown Prince (order
qoder13): this module builds and tests against a STAGING directory only. It
must not be pointed at `/var/www` or wired into nginx until (a) the Emperor
approves the web root and (b) qoder11's `reconcile_adult.py` lands, because a
static JSON is a new public display surface with no runtime gate behind it.

Safe by construction, so publishing is a config change and not a code change:

* **The adult law is in the export query, not bolted on after it.** The row
  clause is `redact.adult_clause` — the one predicate every public emitter
  already shares — AND-ed with the canonical-key twin exclusion (a work with
  any flagged row is a flagged work, 442 keys / 455 works today, see AGENTS.md
  "known hole"). The same exclusion the prefetch worker applies at selection.
* **The suppression is measured and reported**, not assumed: every sweep
  returns how many unflagged works the twin clause removed. If that number
  ever goes to zero in production it means the ledger reconciled; the exporter
  stays correct either way (the clause is belt, reconciliation is braces).
* **Nothing signed ever leaves this module.** No import of `signing_secret`,
  no `mint_token`, no art handles, no stream/download URLs. Rows are projected
  through `redact.project(row, "post_brief")` — the exact allowlist the live
  `/api/v1/posts` response uses, `id` included as the unsigned ledger row id
  redact itself declares publishable — plus artwork ONLY when
  `redact.public_image_value` says the stored URL already sits on a
  third-party public CDN. A scraped site's own image path is dropped, exactly
  as `redact`'s comment on the v1 views demands.
* **Deterministic and atomic.** `json.dumps(sort_keys=True)` and a fully
  ordered SQL (`ORDER BY …, p.id DESC`) mean an unchanged page re-exports
  byte-identical, so no churn and no cache invalidation thunder; each file is
  written to a temp path in its own directory and moved into place with
  `os.replace`, so a reader can never observe a half-written page.

Output layout (under `--out`, default `/tmp/radd-static-stage`):

    home.json                  first page, trending sort (the app's landing)
    browse/{sort}/p{NNNNN}.json  pages 1..N of each shipped sort
    manifest.json              what was written, with the suppression counts

Stdlib only. Usage:

    python3 -S Fast_Fetch/catalog_exporter.py --db path/to.db --pages 20
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import redact  # noqa: E402  (project's own redaction layer — reused, not re-declared)

DEFAULT_STAGING_DIR = "/tmp/radd-static-stage"
DEFAULT_PER_PAGE = 50
DEFAULT_PAGES = 20
#: The sorts the live browse surface offers; mirrored here so a static page and
#: an API answer are the same shape for the same request. `trending` is the
#: release+source-count proxy (`viewer.api_v1_get_posts`' own wording: no
#: play-count column exists, and we refuse to invent one).
SORTS = ("trending", "rating", "title", "recent")

_ORDER_SQL = {
    "trending": "(release_count + source_count) DESC, p.id DESC",
    "rating": "(p.imdb_rating IS NULL OR TRIM(p.imdb_rating) = '') ASC,"
              " CAST(p.imdb_rating AS REAL) DESC, p.id DESC",
    "title": "lower(COALESCE(NULLIF(TRIM(p.clean_title), ''), p.title)) ASC, p.id DESC",
    "recent": "COALESCE(p.lastmod, p.created_at) DESC, p.id DESC",
}

def guarded_posts_where() -> str:
    """The single public-display WHERE for posts, shared with counting.

    Composed from `redact.adult_clause("p")` so there remains exactly one
    definition of the row-level rule in the repo, plus the canonical-key twin
    exclusion which the clause itself does not yet carry (until
    `reconcile_adult.py` folds it into the ledger).
    """
    return (
        f"({redact.adult_clause('p')})"
        " AND (p.canonical_key IS NULL OR NOT EXISTS ("
        "       SELECT 1 FROM posts f"
        "       WHERE f.is_18_plus = 1 AND f.canonical_key = p.canonical_key))"
    )


def count_twin_suppressed(conn: sqlite3.Connection) -> int:
    """Distinct works (canonical keys) the twin clause removes — reported, never silent.

    Counts unflagged ROWS that the row-level `adult_clause` would happily pass
    but whose `canonical_key` names a flagged work: exactly the AGENTS.md
    "455 flagged works reachable under an unflagged twin" population. A work
    with no key is counted by row id, so the number is works, not rows.
    """
    row = conn.execute(
        """
        SELECT COUNT(DISTINCT COALESCE(p.canonical_key, 'id:' || p.id))
        FROM posts p
        WHERE ({adult})
          AND EXISTS (SELECT 1 FROM posts f
                      WHERE f.is_18_plus = 1
                        AND f.canonical_key = p.canonical_key)
        """.format(adult=redact.adult_clause("p"))).fetchone()
    return int(row[0]) if row else 0


def export_page(conn: sqlite3.Connection, sort: str, page: int, per_page: int) -> dict:
    """One browse page, projected through the same view the live API emits."""
    where_sql = guarded_posts_where()
    # The column list is deliberately NARROWER than the `post_brief` view:
    # the live browse route never selects `synopsis` either, and a stored
    # synopsis is scraper prose that can name hosters ("G-Direct", "PikaHD" —
    # proven by sweep_public_edge --export on 2026-11-05), which `scrub_text`
    # cannot remove because its list is curated known brands only. A pre-
    # rendered file has no runtime gate and no curated-list update can reach a
    # copy already cached at the edge, so free prose stays off the export.
    total = conn.execute(
        f"SELECT COUNT(*) FROM posts p WHERE {where_sql}", ()).fetchone()[0]
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = min(max(1, page), total_pages)
    offset = (page - 1) * per_page
    sql = f"""
        SELECT p.id, p.clean_title, p.title, p.year, p.content_type, p.seasons,
               p.poster_url, p.backdrop_urls, p.imdb_rating, p.imdb_id, p.tmdb_id,
               p.genres, p.is_animated, p.industry, p.country, p.language,
               COUNT(DISTINCT r.id) AS release_count,
               COUNT(DISTINCT s.id) AS source_count
        FROM posts p
        LEFT JOIN releases r ON r.post_id = p.id
        LEFT JOIN download_sources s ON s.release_id = r.id
        WHERE {where_sql}
        GROUP BY p.id
        ORDER BY {_ORDER_SQL[sort]}
        LIMIT ? OFFSET ?
    """
    rows = conn.execute(sql, (per_page, offset)).fetchall()
    results = []
    for r in rows:
        item = redact.project(dict(r), "post_brief")
        # Art: the stored URL passes ONLY if its host is a public third-party
        # CDN (`redact.public_image_value`), never as a signed handle — this
        # module has no access to the signing secret by design.
        poster = redact.public_image_value(r["poster_url"])
        if poster:
            item["poster_url"] = poster
        raw = r["backdrop_urls"]
        try:
            imports = json.loads(raw) if raw else []
        except (json.JSONDecodeError, TypeError):
            imports = []
        backdrops = [u for u in (redact.public_image_value(i)
                                 for i in imports if str(i or "").strip()) if u]
        if backdrops:
            item["backdrop_urls"] = backdrops
        results.append(item)
    return {
        "sort": sort,
        "page": page,
        "limit": per_page,
        "total": total,
        "total_pages": total_pages,
        "results": results,
    }


def write_atomic(dir_path: Path, name: str, payload: dict) -> Path:
    """Temp file in the destination directory + os.replace — never a partial page.

    Same-directory is what makes the replace atomic (cross-device renames are
    not); the temp file is removed if anything before the replace fails.
    """
    dir_path.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(dir_path), prefix=f".{name}.", suffix=".tmp")
    try:
        text = json.dumps(payload, sort_keys=True, ensure_ascii=False,
                          separators=(",", ":"))
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        target = dir_path / name
        os.replace(tmp_name, target)
        return target
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def export_catalog(db_path: str, out_dir: str, *, pages: int = DEFAULT_PAGES,
                   per_page: int = DEFAULT_PER_PAGE,
                   sorts: tuple[str, ...] = SORTS,
                   verbose: bool = True) -> dict:
    """Render home + browse pages into `out_dir`; returns the manifest.

    `out_dir` is whatever the caller was authorized to write — the staging
    directory today, and only after the qoder13 gates open, a real web root.
    """
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        suppressed = count_twin_suppressed(conn)
        out_root = Path(out_dir)
        written = []
        # home = first page of the landing sort, duplicated under its own name
        # so a static rule can map `/` without knowing browse's path scheme.
        home = export_page(conn, "trending", 1, per_page)
        written.append(str(write_atomic(out_root, "home.json", home)))
        for sort in sorts:
            sort_dir = out_root / "browse" / sort
            total_pages = min(pages, home["total_pages"])
            for page in range(1, total_pages + 1):
                payload = export_page(conn, sort, page, per_page)
                written.append(str(write_atomic(sort_dir, f"p{page:05d}.json", payload)))
        manifest = {
            "db": str(db_path),
            "pages_per_sort": pages,
            "per_page": per_page,
            "sorts": list(sorts),
            "files": sorted(written),
            # Reported so suppression is a number someone can watch, not a
            # comment someone trusts. This is what qoder13 asks the agent to
            # state after every run.
            "works_suppressed_by_canonical_key_clause": suppressed,
        }
        write_atomic(out_root, "manifest.json", manifest)
        if verbose:
            print(f"[exporter] {len(written)} files -> {out_root}; "
                  f"twin-clause suppressed {suppressed} works")
        return manifest
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1].strip())
    parser.add_argument("--db", required=True, help="catalog database path")
    parser.add_argument("--out", default=DEFAULT_STAGING_DIR,
                        help=f"output directory (default staging: {DEFAULT_STAGING_DIR})")
    parser.add_argument("--pages", type=int, default=DEFAULT_PAGES,
                        help="pages per sort (default 20)")
    parser.add_argument("--per-page", type=int, default=DEFAULT_PER_PAGE)
    parser.add_argument("--sorts", default=",".join(SORTS),
                        help=f"comma list from {SORTS}")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    sorts = tuple(s.strip() for s in args.sorts.split(",") if s.strip() in SORTS)
    if not sorts:
        parser.error(f"no valid sorts in {args.sorts!r}; choose from {SORTS}")
    if str(Path(args.out).resolve()).startswith("/var/www"):
        # qoder13: the web root needs the Emperor's approval and nginx review;
        # this lane does not own that decision and refuses to make it by flag typo.
        parser.error("--out under /var/www is not authorized; export to the "
                     "staging directory and let the publishing gate move files.")
    export_catalog(args.db, args.out, pages=args.pages, per_page=args.per_page,
                   sorts=sorts, verbose=not args.quiet)
    return 0


if __name__ == "__main__":
    sys.exit(main())
