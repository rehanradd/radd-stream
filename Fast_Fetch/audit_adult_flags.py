#!/usr/bin/env python3
"""Sort every `is_18_plus=1` row by the evidence that actually justifies it.

Why this file exists. On 2026-10-29 the key-level adult reconciliation ran against
production and flipped 455 rows from public to hidden. Auditing *why* each of those rows
was flagged answered: 0 justified by their own stored text, 375 only because a sibling
matched a pattern, 80 with no pattern anywhere. The patterns behind the sibling flags
were `\\buncut\\b` (300) and `\\bunrated\\b` (31) — **version labels, not adult markers**,
written by sites whose page slugs read `…-hindi-uncut-hd-download`. 407 of the 455 flips
were mainstream cinema (Kanguva, Hi Nanna, Guntur Kaaram, Dharmaveer 2, Gangs of
Godavari, …) and had to be reversed by hand from a preimage file.

The same measurement over the whole ledger, read-only:

    flagged rows ......................................... 15,068
    justified ONLY by uncut/unrated in stored text .......  7,663   (51% false hides)
    matching NO adult pattern in stored text at all ......  2,647   (tags / raw_meta /
                                                                    a site-wide rule)

The patterns are fixed in `fast_fetch.ADULT_TITLE_PATTERNS`, and the ingest path is now
correct. Its *history* is not: rows written while the poisoned list was live still carry
`is_18_plus=1`. Un-flagging them is an **exposure event** — every row this tool frees
becomes publicly served — so it is report-only by default and refuses to write without
the owner's explicit GO.

Three classes, decided on evidence rather than on a guess:

* `true-adult-in-stored-text` — one of the current `ADULT_TITLE_PATTERNS` matches the
  row's own ledger text (the four fields the flag rule can see, then genres/synopsis).
* `version-word-only` — no adult pattern anywhere in its stored text, but `uncut` or
  `unrated` is present: the word that flagged it. **These are the only un-flag
  candidates.**
* `no-stored-evidence` — nothing in its stored text at all. The evidence for these is
  not in the ledger, so this tool goes and reads the source vault's full raw row
  (`<site>.db` in the staging dir, every column as text). That is how 3 of the 80 were
  justified on 2026-10-29. A row the vault also cannot justify stays flagged and is
  reported, not freed: an unresolved flag is a *review* problem, and a public row is an
  exposure problem.

A candidate is only freed when no OTHER row under the same `canonical_key` carries
true-adult evidence, because the flag is reconciled per key: if one sibling really is
adult, every copy of the work must stay hidden. `unknown` and the empty key are excluded
from the sibling rule — they are the shared bucket every titleless payload lands in, not
one work.

Before a single row is written, the tool writes a **preimage** — `(id, canonical_key,
old flag)` for every row it is about to change — to a file, fsyncs it and re-reads it,
and refuses to proceed if that verification fails. That is the object that made the
2026-10-29 reversal possible, rebuilt as a precondition instead of a rescue.

    python3 -S Fast_Fetch/audit_adult_flags.py <db.path>                     # report
    python3 -S Fast_Fetch/audit_adult_flags.py <db.path> --apply \\
        --owner-go "<the owner's own words>" [--prod] [--projection] [--max-rows N]

Read-only in report mode, and it only ever *lowers* a flag: it cannot hide anything.
Stdlib only. Never run it while a projection is reading the same database.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import fast_fetch

#: The two words that hid 7,663 legitimate works. They are edition vocabulary —
#: `release_descriptor.py` and `catalog_api.py` already file them under `edition` — and
#: they are what a `version-word-only` row is named after.
VERSION_PATTERNS = [r"\buncut\b", r"\bunrated\b"]

#: The ledger columns `save_scraped_data` derives the flag from:
#: `is_adult_title(clean_title or title, original_title or slug or url)`.
DERIVE_COLUMNS = ("title", "clean_title", "slug", "url")

#: Columns that carry evidence about the work but never decided the flag.
WIDE_COLUMNS = DERIVE_COLUMNS + ("genres", "synopsis")

#: The staging vault's raw row is read through every column it has.
VAULT_COLUMNS = ("title", "clean_title", "slug", "url", "synopsis", "genres",
                 "languages", "media_type", "raw_meta")

TRUE_ADULT = "true-adult-in-stored-text"
VERSION_WORD_ONLY = "version-word-only"
VAULT_ADULT = "no-stored-evidence/vault-justified"
UNRESOLVED = "no-stored-evidence/unresolved"

CLASS_ORDER = (TRUE_ADULT, VERSION_WORD_ONLY, VAULT_ADULT, UNRESOLVED)


def match(patterns, text: str) -> str | None:
    """The first pattern that matches `text`, or None."""
    for pattern in patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return pattern
    return None


def row_text(row, columns) -> str:
    return " ".join(str(row[c]) for c in columns
                    if c in row.keys() and row[c] not in (None, ""))


def classify(row) -> tuple[str, str | None]:
    """(class, the pattern or word that put it there) for one flagged ledger row."""
    derive = row_text(row, DERIVE_COLUMNS)
    wide = row_text(row, WIDE_COLUMNS)
    why = match(fast_fetch.ADULT_TITLE_PATTERNS, derive)
    if why:
        return TRUE_ADULT, why
    why = match(fast_fetch.ADULT_TITLE_PATTERNS, wide)
    if why:
        # Only genres or synopsis carries it: real evidence, but it is not what the
        # ingest rule saw, so a flag sitting on this row came from somewhere else.
        return TRUE_ADULT, f"{why} (non-derive field)"
    why = match(VERSION_PATTERNS, wide)
    if why:
        return VERSION_WORD_ONLY, why
    return UNRESOLVED, None


class Vault:
    """One site's staging database, read once, in service of the unresolved rows.

    A vault row is matched to a ledger row by url, then slug, then canonical key: the
    merge copies a site's own identity through, but not every lane wrote the same url.
    Loading the whole table once is deliberate — the vault `posts` table has no index on
    `url`, so per-row lookups would be one full scan per row on a 1-core host.
    """

    def __init__(self, path: Path):
        self.path = path
        self.by_url: dict[str, str] = {}
        self.by_slug: dict[str, str] = {}
        self.by_key: dict[str, str] = {}
        self.rows = 0
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            columns = [r[1] for r in conn.execute("PRAGMA table_info(posts)")]
            wanted = [c for c in VAULT_COLUMNS if c in columns]
            if not wanted:
                return
            for row in conn.execute(f"SELECT {', '.join(wanted)} FROM posts"):
                self.rows += 1
                text = row_text(row, wanted)
                key = str(row["canonical_key"]) if "canonical_key" in row.keys() else None
                if key:
                    self.by_key.setdefault(key, text)
                if "url" in row.keys() and row["url"]:
                    self.by_url.setdefault(str(row["url"]), text)
                if "slug" in row.keys() and row["slug"]:
                    self.by_slug.setdefault(str(row["slug"]), text)
        finally:
            conn.close()

    def text_for(self, row) -> str | None:
        url = str(row["url"] or "") if "url" in row.keys() else ""
        slug = str(row["slug"] or "") if "slug" in row.keys() else ""
        key = str(row["canonical_key"] or "") if "canonical_key" in row.keys() else ""
        return self.by_url.get(url) or self.by_slug.get(slug) or self.by_key.get(key)


class VaultIndex:
    """Vaults opened lazily, only for the sites that have rows to resolve."""

    def __init__(self, vault_dir: Path):
        self.vault_dir = Path(vault_dir)
        self._cache: dict[str, Vault | None] = {}
        self.loaded: list[tuple[str, int]] = []

    def text_for(self, row) -> str | None:
        site = str(row["source_site"] or "").strip().lower() if "source_site" in row.keys() else ""
        if not site:
            return None
        if site not in self._cache:
            path = self.vault_dir / f"{site}.db"
            if not path.exists():
                self._cache[site] = None
            else:
                vault = Vault(path)
                self._cache[site] = vault
                self.loaded.append((site, vault.rows))
        vault = self._cache[site]
        return vault.text_for(row) if vault else None


def siblings_are_clear(conn, key: str, self_id: int, vaults: VaultIndex | None,
                       columns: list[str]) -> tuple[bool, str | None, int]:
    """Any OTHER row under `key` carrying true-adult evidence, and how many stay flagged.

    One bounded statement per key, resolved by `idx_posts_canonical_key` rather than by
    scanning the table, and it stops at the first hit: finding evidence is all we need.
    The flagged-sibling count rides along for free and is what reports the keys this run
    would leave mixed — one copy served, one still hidden.
    """
    if not key or key == "unknown":
        return (True, None, 0)
    select = ", ".join(columns)
    flagged_siblings = 0
    for sibling in conn.execute(
            f"SELECT {select} FROM posts"
            " WHERE canonical_key = ? AND id <> ? AND COALESCE(is_18_plus, 0) = 1",
            (key, self_id)):
        flagged_siblings += 1
        kind, why = classify(sibling)
        if kind == TRUE_ADULT:
            return (False, f"sibling {sibling['id']} {why}", flagged_siblings)
        if kind == UNRESOLVED and vaults is not None:
            text = vaults.text_for(sibling)
            if text and match(fast_fetch.ADULT_TITLE_PATTERNS, text):
                return (False, f"sibling {sibling['id']} vault raw row", flagged_siblings)
    return (True, None, flagged_siblings)


def ledger_columns(conn) -> list[str]:
    """The columns this ledger actually has, in the order the audit wants them.

    Staging databases and the merged catalog were written by different lanes, so the
    audit composes its own SELECT rather than assuming `SELECT *` shape — a missing
    `synopsis` is a narrower evidence base, not a crash.
    """
    have = {row[1] for row in conn.execute("PRAGMA table_info(posts)")}
    wanted = ["id", "canonical_key", "source_site", "is_18_plus", *WIDE_COLUMNS]
    return [name for name in dict.fromkeys(wanted) if name in have]


def audit(conn, *, vault_dir: Path | None, check_siblings: bool = True,
          require_clean_siblings: bool = False) -> dict:
    """Read-only classification of every flagged row, and what would be freed."""
    vaults = VaultIndex(vault_dir) if vault_dir else None
    columns = ledger_columns(conn)
    counts = {name: 0 for name in CLASS_ORDER}
    examples = {name: [] for name in CLASS_ORDER}
    blocked_adult_sibling = 0
    blocked_unresolved_sibling = 0
    mixed_keys = 0
    candidates = []
    flagged = 0
    select = ", ".join(columns)
    #: Streamed, not materialised: 15,068 rows of synopsis text is tens of megabytes on
    #: a 1-core host that is also serving the API.
    for row in conn.execute(f"SELECT {select} FROM posts WHERE COALESCE(is_18_plus, 0) = 1"):
        flagged += 1
        kind, why = classify(row)
        if kind == UNRESOLVED and vaults is not None:
            text = vaults.text_for(row)
            if text and match(fast_fetch.ADULT_TITLE_PATTERNS, text):
                kind, why = VAULT_ADULT, "vault raw row"
        counts[kind] += 1
        if len(examples[kind]) < 12:
            examples[kind].append({"id": row["id"], "key": row["canonical_key"],
                                   "title": str(row["title"] or "")[:70], "why": why})
        if kind != VERSION_WORD_ONLY:
            continue
        if check_siblings:
            clear, reason, flagged_siblings = siblings_are_clear(
                conn, str(row["canonical_key"] or ""), int(row["id"]), vaults, columns)
        else:
            clear, reason, flagged_siblings = (True, None, 0)
        if not clear:
            blocked_adult_sibling += 1
            continue
        if flagged_siblings:
            mixed_keys += 1
            if require_clean_siblings:
                # The tighter law: free nothing whose key still carries another flagged
                # row, even one this audit could not justify. Without it a mixed key is
                # reported, not prevented, and the work is served through the freed copy.
                blocked_unresolved_sibling += 1
                continue
        candidates.append({"id": int(row["id"]),
                           "canonical_key": str(row["canonical_key"] or ""),
                           "is_18_plus": 1, "title": row["title"], "why": why})
    return {"flagged": flagged, "counts": counts, "examples": examples,
            "candidates": candidates, "blocked_sibling_adult": blocked_adult_sibling,
            "blocked_sibling_unresolved": blocked_unresolved_sibling,
            "mixed_keys_after": mixed_keys,
            "vaults_loaded": vaults.loaded if vaults else []}


def public_total(conn) -> int:
    import redact
    return int(conn.execute(
        f"SELECT COUNT(*) FROM posts WHERE {redact.adult_clause('posts')}").fetchone()[0] or 0)


def write_preimage(path: Path, result: dict, db_path: Path, owner_go: str) -> list[dict]:
    """Write and verify the preimage, and return the rows it covers.

    Verification is not a courtesy: the 2026-10-29 reversal was possible *only* because
    this file existed and was complete. An unverified preimage is not a rollback point,
    so a mismatch here aborts the whole run before any UPDATE.
    """
    rows = [{"id": c["id"], "canonical_key": c["canonical_key"], "is_18_plus": 1}
            for c in result["candidates"]]
    payload = {"created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "db": str(db_path), "owner_go": owner_go, "rows": rows}
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=1)
        handle.flush()
        os.fsync(handle.fileno())
    written = json.loads(path.read_text(encoding="utf-8"))
    if [r["id"] for r in written["rows"]] != [r["id"] for r in rows]:
        raise SystemExit(f"[!] preimage verification failed: {path} does not hold every "
                         f"row about to change; nothing was written")
    return rows


def apply_unflags(conn, rows: list[dict]) -> int:
    """Lower the flag on exactly the preimaged ids, inside one transaction."""
    cur = conn.executemany(
        "UPDATE posts SET is_18_plus = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        [(row["id"],) for row in rows])
    return max(int(cur.rowcount or 0), 0)


#: A work's projection flag can only change if one of the rows just freed folds into it,
#: so the re-roll is bounded by the freed set through a temp table — never a scan of
#: every `cat_works` row with a correlated subquery twice per row on a 1-core host.
PROJECTION_SQL = (
    "UPDATE cat_works SET is_18_plus = ("
    "  EXISTS (SELECT 1 FROM cat_work_sites s JOIN posts p ON p.id = s.post_id"
    "          WHERE s.work_id = cat_works.id AND COALESCE(p.is_18_plus, 0) = 1))"
    " WHERE id IN (SELECT work_id FROM cat_work_sites"
    "              WHERE post_id IN (SELECT post_id FROM audit_freed))"
    "   AND is_18_plus <> ("
    "  EXISTS (SELECT 1 FROM cat_work_sites s JOIN posts p ON p.id = s.post_id"
    "          WHERE s.work_id = cat_works.id AND COALESCE(p.is_18_plus, 0) = 1))"
)

#: Adult-excluded counters `/api/v1/stats` publishes; a flag change invalidates all of
#: them, and the endpoint recounts live when a stamp is missing.
SAFE_STAMP_KEYS = ("works_safe", "adult_works", "releases_safe", "links_safe",
                   "links_active_safe", "links_resumable_safe", "links_temporary_safe",
                   "links_by_state_safe")


def apply_projection(conn, freed_ids: list[int]) -> tuple[int, int]:
    if not all(conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                            (name,)).fetchone()
               for name in ("cat_works", "cat_work_sites", "cat_projection_meta")):
        print("[!] no projection in this database — run catalog_v2.project() instead")
        return (0, 0)
    conn.execute("CREATE TEMP TABLE audit_freed (post_id INTEGER PRIMARY KEY)")
    conn.executemany("INSERT INTO audit_freed (post_id) VALUES (?)",
                     [(int(pid),) for pid in freed_ids])
    changed = max(int(conn.execute(PROJECTION_SQL).rowcount or 0), 0)
    marks = ",".join("?" * len(SAFE_STAMP_KEYS))
    dropped = conn.execute(
        f"DELETE FROM cat_projection_meta WHERE key IN ({marks})", SAFE_STAMP_KEYS).rowcount
    return (changed, dropped)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("db", type=Path)
    parser.add_argument("--apply", action="store_true",
                        help="write the un-flags (default: report only)")
    parser.add_argument("--owner-go", default=None,
                        help="the owner's own words authorising this exposure event; "
                             "required with --apply and recorded in the preimage")
    parser.add_argument("--prod", action="store_true",
                        help="required, in addition to --owner-go, when the target is "
                             "the live catalog under the staging data dir")
    parser.add_argument("--max-rows", type=int, default=None,
                        help="write at most N candidates, for a staged first tranche")
    parser.add_argument("--projection", action="store_true",
                        help="with --apply, also re-roll cat_works.is_18_plus and "
                             "retire the adult-excluded stats stamps")
    parser.add_argument("--vault-dir", type=Path, default=None,
                        help="staging vaults to resolve the no-stored-evidence class "
                             "from (default: the configured staging data dir)")
    parser.add_argument("--no-vaults", action="store_true",
                        help="classify from ledger text only")
    parser.add_argument("--require-clean-siblings", action="store_true",
                        help="free nothing whose key still carries another flagged row, "
                             "even one this audit could not justify")
    parser.add_argument("--preimage", type=Path, default=None)
    parser.add_argument("--journal", type=Path, default=None,
                        help="write the per-row decisions next to the preimage")
    args = parser.parse_args(argv)

    if not args.db.exists():
        print(f"[!] no such database: {args.db}", file=sys.stderr)
        return 2

    import config
    vault_dir = None if args.no_vaults else (args.vault_dir or config.DATA_DIR)
    is_prod = args.db.resolve().parent == Path(config.DATA_DIR).resolve() or \
        str(args.db.resolve()) == str(Path(config.DB_PATH).resolve())
    if args.apply and not args.owner_go:
        print("[!] refusing --apply without --owner-go: un-flagging is an exposure "
              "event and the owner authorises it, not this tool", file=sys.stderr)
        return 2
    if args.apply and is_prod and not args.prod:
        print(f"[!] refusing to write {args.db} (it is the live catalog) without --prod",
              file=sys.stderr)
        return 2

    started = time.time()
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        before = public_total(conn)
        result = audit(conn, vault_dir=vault_dir,
                       require_clean_siblings=args.require_clean_siblings)
        print(f"[i] {args.db}")
        print(f"[i] flagged rows {result['flagged']:,}")
        for name in CLASS_ORDER:
            print(f"      {name:<32} {result['counts'][name]:>7,}")
        if vault_dir:
            for site, n in result["vaults_loaded"]:
                print(f"      [vault] {site}: {n:,} raw rows read")
        else:
            print("      [!] vaults not read: the no-stored-evidence class is unresolved")
        print(f"[i] un-flag candidates {len(result['candidates']):,} "
              f"(blocked: {result['blocked_sibling_adult']:,} with a true-adult sibling"
              f", {result['blocked_sibling_unresolved']:,} with an unresolved sibling)")
        print(f"[i] keys this run would leave MIXED (one copy freed, another still "
              f"flagged): {result['mixed_keys_after']:,}"
              + ("" if args.require_clean_siblings else
                 " — pass --require-clean-siblings to hold those rows back"))
        if args.max_rows is not None and len(result["candidates"]) > args.max_rows:
            print(f"[i] --max-rows {args.max_rows}: the first {args.max_rows} by id are "
                  f"selected, the rest wait for a later tranche")
            result["candidates"] = result["candidates"][:args.max_rows]
        for name in CLASS_ORDER:
            for example in result["examples"][name][:3]:
                print(f"      {name:<28} id={example['id']} "
                      f"{example['title']!r} <- {example['why']}")

        journal = args.journal or args.db.with_suffix(".adult_audit_journal.txt")
        with open(journal, "w", encoding="utf-8") as handle:
            handle.write(json.dumps({"db": str(args.db), "counts": result["counts"],
                                     "examples": result["examples"]}, indent=1))
            for candidate in result["candidates"]:
                handle.write(f"CANDIDATE {candidate['id']}\t{candidate['canonical_key']}"
                             f"\t{candidate['why']}\t{candidate['title']}\n")
        print(f"[i] journal: {journal}")
        if not args.apply:
            print("[i] report only; --apply requires --owner-go and writes a preimage "
                  "before it touches a row")
            return 0

        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        preimage = args.preimage or args.db.with_name(
            f"adult_unflag_preimage_{stamp}.json")
        rows = write_preimage(preimage, result, args.db, args.owner_go)
        print(f"[✓] preimage written and verified: {preimage} ({len(rows):,} rows)")

        flipped = apply_unflags(conn, rows)
        after = public_total(conn)
        if flipped != len(rows) or after - before != len(rows):
            print(f"[!] VERIFICATION FAILED: {flipped} rows written, {len(rows)} intended, "
                  f"public total {before:,} -> {after:,}", file=sys.stderr)
            conn.rollback()
            print(f"[i] nothing was committed. The preimage is kept on purpose — it "
                  f"describes the state the database is still in: {preimage}",
                  file=sys.stderr)
            return 1
        if args.projection:
            changed, dropped = apply_projection(conn, [row["id"] for row in rows])
            print(f"[✓] projection: {changed:,} works re-rolled; {dropped:,} "
                  f"adult-excluded stamps retired")
        conn.commit()
        with open(journal, "a", encoding="utf-8") as handle:
            handle.write(f"APPLIED {datetime.now(timezone.utc).isoformat(timespec='seconds')}"
                         f"\tflipped={flipped}\tpreimage={preimage}\t"
                         f"public_total={before}->{after}\n")
        print(f"[✓] {flipped:,} rows un-flagged; public total {before:,} -> {after:,} "
              f"(exactly the rows freed). Roll back from {preimage}.")
        return 0
    finally:
        print(f"[i] {time.time() - started:.1f}s", flush=True)
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
