"""The FTS5 search index over the projected catalog (Session 123).

`catalog_api._run_listing` already accelerates v2 search with
`w.id IN (SELECT rowid FROM cat_works_fts WHERE cat_works_fts MATCH :fts)`
whenever the table exists, and falls back to the ANDed LIKE scan when it does
not — but nothing ever created the table, so every search paid the LIKE scan
(the scale plan's "49s cold search"). This module is the missing half: it
creates the table and fills it. The search wiring is untouched.

The index is a standalone FTS5 table (it stores its own copy of the
normalised text — a few megabytes against a multi-gigabyte catalog), not an
external-content table: the four indexed columns do not all live in one
table (`aliases` comes from `cat_work_aliases`), and an external-content
table maps its columns by name onto a single content table, so it cannot
hold them. It is populated wholesale by `rebuild_fts`, which the projector
runs at the end of `_finalize`, when `cat_works` and `cat_work_aliases` are
final. No triggers: the projection is rebuilt from scratch on every rev, so
a trigger would only add write load to the big insert pass for an index the
next line rebuilds anyway. Rowids are the work ids, which is what the search
reads back (`w.id IN (SELECT rowid ...)`).

What is indexed is exactly the haystack the LIKE fallback searches, so the
accelerator can never hide a row the fallback would have found: `title`,
`original_title`, `genres`, and the work's aliases (one space-joined string
per work). Every field is stored NORMALISED — the same rule
`catalog_api.normalize_text` applies to the query (casefold, diacritics
folded, punctuation to spaces) — because the FTS tokenizer does not fold
diacritics: indexing raw text would make "amelie" miss "Amélie" while the
LIKE path finds it, and an accelerator that loses results is a regression,
not a speedup. The twin normaliser here is pinned equal to the catalog
module's by a test. The index stores search text, never display text: what a
client sees still comes from `cat_works`.

An empty index is worse than no index: `_has_table` alone would switch the
search onto a MATCH that returns nothing. `rebuild_fts` therefore always
creates AND fills in one call, and the projector treats a failure to build it
as a warning, never a gate — the search falls back to LIKE, which is the
behaviour the catalog has shipped with all along.
"""
from __future__ import annotations

import re
import sqlite3
import unicodedata

#: The FTS columns, in the same order the LIKE haystack searches them.
FTS_COLUMNS = ("title", "original_title", "genres", "aliases")

_NON_WORD_RE = re.compile(r"[^\w\s]", flags=re.UNICODE)
_MULTI_SPACE_RE = re.compile(r"\s+")


def normalize_text(text) -> str:
    """Twin of `catalog_api.normalize_text`, kept local so this module has no
    import cycle with the catalog API (the projector imports this module, and
    the catalog API imports the projector). Pinned equal by a test."""
    if text in (None, ""):
        return ""
    folded = unicodedata.normalize("NFKD", str(text))
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    folded = folded.casefold()
    folded = folded.replace("&", " and ")
    folded = _NON_WORD_RE.sub(" ", folded)
    return " ".join(_MULTI_SPACE_RE.split(folded.strip()))


def ensure_fts(conn: sqlite3.Connection) -> None:
    """Create the standalone FTS5 table, if it does not exist yet."""
    columns = ", ".join(FTS_COLUMNS)
    conn.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS cat_works_fts USING fts5("
        f"{columns}, tokenize='unicode61')")


def fts_available(conn: sqlite3.Connection) -> bool:
    """True when the index exists and holds at least one work.

    The search hot path checks existence only; this is the health check a
    caller uses when it needs to know the index can actually answer.
    """
    row = conn.execute(
        "SELECT name FROM sqlite_master"
        " WHERE type = 'table' AND name = 'cat_works_fts'").fetchone()
    if row is None:
        return False
    return int(conn.execute("SELECT COUNT(*) FROM cat_works_fts").fetchone()[0]) > 0


def rebuild_fts(conn: sqlite3.Connection, *, batch_size: int = 5000) -> dict:
    """Rebuild the whole index from the current projection.

    Deletes the index, then re-inserts one row per work with its normalised
    fields and its space-joined aliases. Returns the counts so the projector
    can log them. A projection with zero works leaves a valid empty index.
    """
    ensure_fts(conn)
    conn.execute("DELETE FROM cat_works_fts")
    cursor = conn.execute(
        """
        SELECT w.id, w.title, w.original_title, w.genres,
               (SELECT group_concat(a.alias, ' ') FROM cat_work_aliases a
                 WHERE a.work_id = w.id)
          FROM cat_works w ORDER BY w.id
        """)
    indexed = 0
    while True:
        rows = cursor.fetchmany(batch_size)
        if not rows:
            break
        conn.executemany(
            "INSERT INTO cat_works_fts (rowid, title, original_title,"
            " genres, aliases) VALUES (?, ?, ?, ?, ?)",
            [(int(work_id), normalize_text(title), normalize_text(original),
              normalize_text(genres), normalize_text(aliases))
             for work_id, title, original, genres, aliases in rows])
        indexed += len(rows)
    conn.commit()
    return {"works": indexed, "indexed": indexed}


def search_ids(conn: sqlite3.Connection, query_tokens: list[str]) -> list[int]:
    """The work ids an FTS MATCH answers for already-normalised tokens.

    The same prefix-per-token shape `catalog_api` builds (`"token"*`, ANDed
    by the space join). Raises `sqlite3.OperationalError` when the table is
    absent — the caller falls back to the LIKE scan, as the listing does.
    """
    fts = " ".join(f'"{token}"*' for token in query_tokens if token)
    if not fts:
        return []
    rows = conn.execute(
        "SELECT rowid FROM cat_works_fts WHERE cat_works_fts MATCH ?",
        (fts,)).fetchall()
    return [int(row[0]) for row in rows]
