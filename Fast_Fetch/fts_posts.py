"""The FTS5 search index over `posts` — the benchmark winner (2026-11-12).

The search-performance benchmark (`goals/radd-stream-on-oracle-vm/
hidden_files/search-performance-20261112.md`) measured the current
4x leading-wildcard LIKE at ~1,000 ms per search on the live 224k-post
catalog, and FTS5 (unicode61) on `clean_title` + `cast_names` at
0.13 ms (`salaar`) to 26 ms (`pushpa 2`) — 40x-8,500x faster, with
better bm25 relevance than the year-based baseline ordering. This
module owns that index: the two tables, their sync triggers, the
rebuild/verify the migration script drives, and the MATCH builders the
search path calls.

The two tables (§4.1 of the benchmark):

* `fts_posts` — unicode61, external content over `posts`
  (`clean_title`, `cast_names`, `content_rowid='id'`). One MATCH
  covers title + cast, so the actor search the omnibox promises
  (`shah rukh khan` → 92 cast rows) keeps working. `remove_diacritics
  2` folds `é` → `e` at index time; the query tokenizer here folds
  the same way, so `amelie` finds `Amélie`.
* `fts_posts_tri` — trigram, external content over `posts`
  (`clean_title`, `cast_names`). Two consumers: the typo-correction
  engine (`did_you_mean` / fuzzy candidates) and the `/api/v1/posts`
  substring search, whose four-column LIKE the trigram MATCH replaces
  as a candidate pass — a row whose title, slug or cast contains the
  query contains every 3-gram of it, so the MATCH is a superset and
  the LIKE only verifies the candidates. Trigram as the main index is
  slower on common words and ranks worse, so it never answers a
  search on its own, only as the candidate pass above. The correction
  engine still verifies against `clean_title` only, so a cast match
  never becomes a suggested title.

Freshness: the standard external-content triggers (`_ai`/`_ad`/`_au`
per table) keep both tables in step on every `posts` write. The
initial build is the migration script's job
(`migrate_search_indexes.py --with-fts-posts`, ~13 s on the live
catalog); nothing here builds an index at request time — a 224k-row
rebuild inside a search would stall the service, and an empty index
is worse than no index. The search path therefore treats a missing
or empty index as "fall back to the LIKE scan", never as an error:
`fts_available` / `trigram_available` check existence AND
non-emptiness (via the `_docsize` shadow table — `COUNT(*) FROM
fts_posts` reads `posts`, not the index, so it cannot prove
anything; see `migrate_search_indexes.py`).

Query shape (§4.2): tokens are `[a-z0-9]+` after diacritic folding
(the same tokenizer `search_fuzzy.tokenize` uses, plus the fold).
The MATCH is `token1 AND token2 AND ... AND last_token*` — a
prefix `*` on the LAST token only (search-as-you-type), earlier
tokens exact, which keeps multi-word queries precise. A
whole-word query (one stopword / 1-2 letter token — `the` must not
match `other`) is a single quoted token with no prefix: FTS5
tokenizes on word boundaries, so `MATCH '"the"'` IS the whole-word
match, with no LIKE clause needed. No `ORDER BY rank` anywhere on
the candidate path: the caller groups and sorts by its own sort
key, and ranking is what makes the stopword case cost 332 ms — a
bare posting-list read for `the` is an order of magnitude cheaper.

Stdlib only.
"""

from __future__ import annotations

import re
import sqlite3
import time
import unicodedata

#: The main search index: title + cast, one MATCH answers both.
FTS_TABLE = "fts_posts"
#: The trigram candidate index: titles + cast, for the typo-correction
#: engine and the /posts substring search. `cast_names` joined the
#: index with the /posts candidate pass (2026-11-13): without it the
#: trigram MATCH is not a superset of the search's four-column LIKE,
#: and a cast-only row would be dropped from the candidates.
TRI_TABLE = "fts_posts_tri"
FTS_COLUMNS = ("clean_title", "cast_names")
TRI_COLUMNS = ("clean_title", "cast_names")
#: Sync triggers, one set per table (`_ai`/`_ad`/`_au`).
TRIGGERS = (
    "fts_posts_ai", "fts_posts_ad", "fts_posts_au",
    "fts_posts_tri_ai", "fts_posts_tri_ad", "fts_posts_tri_au",
)

#: unicode61 with diacritic folding, so the index and the query
#: tokenizer agree on `amelie` == `Amélie` (the same reason
#: `migrate_search_indexes.py` uses it for `posts_fts`).
FTS_SQL = (
    f"CREATE VIRTUAL TABLE IF NOT EXISTS {FTS_TABLE} USING fts5("
    f"{', '.join(FTS_COLUMNS)}, content='posts', content_rowid='id', "
    f"tokenize='unicode61 remove_diacritics 2')")
TRI_SQL = (
    f"CREATE VIRTUAL TABLE IF NOT EXISTS {TRI_TABLE} USING fts5("
    f"{', '.join(TRI_COLUMNS)}, content='posts', content_rowid='id', "
    f"tokenize='trigram')")

#: The `new.` / `old.` value lists the sync triggers insert — derived
#: from the column tuples above, never hardcoded, so a column added to
#: either index cannot leave a trigger inserting the wrong arity. A
#: mismatch fails at fire time, not at creation, so a stale trigger
#: breaks the next `posts` write, not the migration that made it.
_FTS_NEW = ", ".join("new." + column for column in FTS_COLUMNS)
_FTS_OLD = ", ".join("old." + column for column in FTS_COLUMNS)
_TRI_NEW = ", ".join("new." + column for column in TRI_COLUMNS)
_TRI_OLD = ", ".join("old." + column for column in TRI_COLUMNS)

TRIGGER_SQL = (
    f"CREATE TRIGGER IF NOT EXISTS {TRIGGERS[0]} AFTER INSERT ON posts BEGIN"
    f"  INSERT INTO {FTS_TABLE}(rowid, {', '.join(FTS_COLUMNS)})"
    f"  VALUES (new.id, {_FTS_NEW}); END",
    f"CREATE TRIGGER IF NOT EXISTS {TRIGGERS[1]} AFTER DELETE ON posts BEGIN"
    f"  INSERT INTO {FTS_TABLE}({FTS_TABLE}, rowid, {', '.join(FTS_COLUMNS)})"
    f"  VALUES ('delete', old.id, {_FTS_OLD}); END",
    f"CREATE TRIGGER IF NOT EXISTS {TRIGGERS[2]} AFTER UPDATE ON posts BEGIN"
    f"  INSERT INTO {FTS_TABLE}({FTS_TABLE}, rowid, {', '.join(FTS_COLUMNS)})"
    f"  VALUES ('delete', old.id, {_FTS_OLD});"
    f"  INSERT INTO {FTS_TABLE}(rowid, {', '.join(FTS_COLUMNS)})"
    f"  VALUES (new.id, {_FTS_NEW}); END",
    f"CREATE TRIGGER IF NOT EXISTS {TRIGGERS[3]} AFTER INSERT ON posts BEGIN"
    f"  INSERT INTO {TRI_TABLE}(rowid, {', '.join(TRI_COLUMNS)})"
    f"  VALUES (new.id, {_TRI_NEW}); END",
    f"CREATE TRIGGER IF NOT EXISTS {TRIGGERS[4]} AFTER DELETE ON posts BEGIN"
    f"  INSERT INTO {TRI_TABLE}({TRI_TABLE}, rowid, {', '.join(TRI_COLUMNS)})"
    f"  VALUES ('delete', old.id, {_TRI_OLD}); END",
    f"CREATE TRIGGER IF NOT EXISTS {TRIGGERS[5]} AFTER UPDATE ON posts BEGIN"
    f"  INSERT INTO {TRI_TABLE}({TRI_TABLE}, rowid, {', '.join(TRI_COLUMNS)})"
    f"  VALUES ('delete', old.id, {_TRI_OLD});"
    f"  INSERT INTO {TRI_TABLE}(rowid, {', '.join(TRI_COLUMNS)})"
    f"  VALUES (new.id, {_TRI_NEW}); END",
)

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def query_tokens(query: str) -> list[str]:
    """The `[a-z0-9]+` tokens of a query, diacritics folded.

    The same token shape `search_fuzzy.tokenize` produces, plus the
    NFKD fold the index's `remove_diacritics 2` tokenizer applies —
    without the fold here, `amelie` would never match the folded
    `amelie` token the index holds for `Amélie`.
    """
    folded = unicodedata.normalize("NFKD", str(query or ""))
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    return _TOKEN_RE.findall(folded.lower())


def build_match(query: str, *, whole_word: bool = False) -> str:
    """The FTS5 MATCH expression for a query, or "" when it has no tokens.

    `token1 AND token2 AND ... AND last_token*` — prefix `*` on the
    last token only. A whole-word query (one stopword / 1-2 letter
    token) is a single quoted token with no prefix: exact-token
    match, which is the whole-word rule by construction. Tokens are
    `[a-z0-9]+` by construction, so no quoting escape is possible.
    """
    tokens = query_tokens(query)
    if not tokens:
        return ""
    if whole_word and len(tokens) == 1:
        return '"%s"' % tokens[0]
    parts = ['"%s"' % token for token in tokens[:-1]]
    parts.append('"%s"*' % tokens[-1])
    return " AND ".join(parts)


def trigram_match(grams: list[str]) -> str:
    """The FTS5 MATCH expression for a trigram candidate pass.

    OR over the query's 3-grams: a title word one edit away shares
    at least one gram with the query token (same recall as the
    LIKE-gram scan this replaces — the same grams, the same OR), and
    the caller orders by `rank` so rows sharing more grams surface
    first. A gram is `[a-z0-9]{3}`, so no quoting escape is possible.
    """
    grams = sorted({gram for gram in grams if gram})
    if not grams:
        return ""
    return " OR ".join('"%s"' % gram for gram in grams)


def _has_table(conn, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view')"
        " AND name = ?", (name,)).fetchone() is not None


def _index_has_rows(conn, table: str) -> bool:
    """True when the index's own shadow table holds at least one row.

    `COUNT(*) FROM <fts>` reads the content table, not the index —
    it cannot prove the index is populated. The `_docsize` shadow
    table is the honest count (see `migrate_search_indexes.py`).
    A missing or damaged shadow table is "not available", never an
    exception on the search path.
    """
    try:
        row = conn.execute(
            f"SELECT 1 FROM {table}_docsize LIMIT 1").fetchone()
    except sqlite3.Error:
        return False
    return row is not None


def fts_available(conn) -> bool:
    """True when the main index exists and holds at least one post.

    The search hot path checks this, not just existence: an index
    created but not yet rebuilt is empty, and an empty index would
    answer every search with nothing. Absent or empty → the caller
    falls back to the LIKE scan.
    """
    return _has_table(conn, FTS_TABLE) and _index_has_rows(conn, FTS_TABLE)


def trigram_available(conn) -> bool:
    """True when the trigram correction index exists and is populated."""
    return _has_table(conn, TRI_TABLE) and _index_has_rows(conn, TRI_TABLE)


def _tri_columns(conn) -> set[str]:
    """The trigram table's indexed columns, or empty when it is absent.

    `PRAGMA table_info` on an FTS5 virtual table reports the columns
    the table was created with — the shape the live index actually
    has, which lags the code's `TRI_COLUMNS` until a rebuild.
    """
    try:
        rows = conn.execute(
            f"PRAGMA table_info({TRI_TABLE})").fetchall()
    except sqlite3.Error:
        return set()
    return {str(row[1]) for row in rows}


def trigram_covers_cast(conn) -> bool:
    """True when the trigram index can answer a cast substring search.

    The candidate pass for `/api/v1/posts` needs the trigram MATCH to
    be a superset of the search's four-column LIKE — title, slug and
    cast. A trigram table built before `cast_names` joined the index
    (the live shape until a rebuild) covers titles only, so it must
    not be trusted for the search: False means "fall back to the LIKE
    scan", never an error.
    """
    return (trigram_available(conn)
            and "cast_names" in _tri_columns(conn))


def _tri_shape_stale(conn) -> bool:
    """True when the trigram table exists but not with `TRI_COLUMNS`."""
    return (_has_table(conn, TRI_TABLE)
            and _tri_columns(conn) != set(TRI_COLUMNS))


def search_candidate_ids(conn, query: str, *, whole_word: bool = False,
                         ) -> list[int] | None:
    """The post ids an FTS5 MATCH answers for `query`.

    Returns None when the index cannot answer (absent, empty, or a
    read error) — the caller falls back to the LIKE scan. Returns []
    when the query has no tokens at all (empty / punctuation-only):
    that is the empty-query guard, and it never runs a scan — the
    LIKE fallback for such a query would walk the whole table to
    answer nothing. No adult clause here, by design: the works
    grouping reads flagged rows deliberately and applies the
    work-level corroborated rule itself. No ORDER BY: the caller
    groups and sorts by its own sort key, and ranking is what makes
    the stopword case expensive.
    """
    if not fts_available(conn):
        return None
    match = build_match(query, whole_word=whole_word)
    if not match:
        return []
    try:
        rows = conn.execute(
            f"SELECT rowid FROM {FTS_TABLE} WHERE {FTS_TABLE} MATCH ?",
            (match,)).fetchall()
    except sqlite3.Error:
        return None
    return [int(row[0]) for row in rows]


def trigram_candidate_ids(conn, match: str, limit: int) -> list[int] | None:
    """The post ids a trigram MATCH answers, best first (bm25 `rank`).

    The trigram candidate pass — the correction layer's and the
    `/api/v1/posts` search's: rows sharing the most query trigrams
    first, so the true title word survives a bounded window (the
    LIKE-gram pass ordered by gram-score for the same reason).
    Returns None when the trigram index cannot answer — the caller
    falls back to the LIKE-gram scan.
    """
    if not match:
        return []
    if not trigram_available(conn):
        return None
    try:
        rows = conn.execute(
            f"SELECT rowid FROM {TRI_TABLE} WHERE {TRI_TABLE} MATCH ?"
            " ORDER BY rank LIMIT ?",
            (match, int(limit))).fetchall()
    except sqlite3.Error:
        return None
    return [int(row[0]) for row in rows]


def ensure_fts(conn) -> None:
    """Create both FTS5 tables and their six sync triggers, if absent.

    Creates only — it never fills: a fresh table is empty, and
    `fts_available` stays False until `rebuild_fts` runs, so the
    search keeps answering from LIKE in between.
    """
    conn.execute(FTS_SQL)
    conn.execute(TRI_SQL)
    for statement in TRIGGER_SQL:
        conn.execute(statement)


def _count(conn, table: str) -> int:
    try:
        return int(conn.execute(
            f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    except sqlite3.Error:
        return -1


def rebuild_fts(conn) -> dict:
    """Rebuild both indexes wholesale from the current `posts` table.

    The migration's build path (and the merge step's, if it is wired
    there): `rebuild` recomputes each external-content index from
    `posts`, so a write landing mid-rebuild is counted once by the
    trigger that follows — triggers are installed after the rebuild,
    the same order `migrate_search_indexes.py` uses for `posts_fts`.
    Returns the counts and the wall time so the caller can log them.
    Benchmark: 7.6 s (main) + 5.1 s (trigram) on 224,081 rows.

    Shape migration: a trigram table built before `cast_names` joined
    `TRI_COLUMNS` still indexes titles only, and its sync triggers
    still insert one column. A trigger that inserts the wrong arity
    fails at fire time, not at creation, so the stale tri triggers
    are dropped FIRST — no `posts` write can fire one against a table
    being reshaped — then the table is dropped and recreated with the
    current columns, the indexes are rebuilt, and all six triggers
    are reinstalled, all before the single commit below, so no writer
    ever sees a half-migrated state.
    """
    ensure_fts(conn)
    for trigger in TRIGGERS[3:]:
        conn.execute(f"DROP TRIGGER IF EXISTS {trigger}")
    if _tri_shape_stale(conn):
        conn.execute(f"DROP TABLE IF EXISTS {TRI_TABLE}")
        conn.execute(TRI_SQL)
    started = time.perf_counter()
    conn.execute(f"INSERT INTO {FTS_TABLE}({FTS_TABLE}) VALUES('rebuild')")
    conn.execute(f"INSERT INTO {TRI_TABLE}({TRI_TABLE}) VALUES('rebuild')")
    for statement in TRIGGER_SQL:
        conn.execute(statement)
    conn.commit()
    took = time.perf_counter() - started
    posts = _count(conn, "posts")
    return {
        "posts": posts,
        "fts_rows": _count(conn, f"{FTS_TABLE}_docsize"),
        "tri_rows": _count(conn, f"{TRI_TABLE}_docsize"),
        "seconds": round(took, 1),
    }


def verify_fts(conn) -> list[str]:
    """The failures that make the index untrustworthy, or [] when it is sound.

    The same two signals `migrate_search_indexes.py` uses for
    `posts_fts`: the `_docsize` shadow counts (not `COUNT(*) FROM
    <fts>`, which reads `posts`) and a token probe from sampled
    rows, plus the trigger check. A failure here means "fall back
    to LIKE and rebuild", never "answer from a lying index".
    """
    failures: list[str] = []
    if not _has_table(conn, FTS_TABLE):
        failures.append(f"{FTS_TABLE} missing")
        return failures
    if not _has_table(conn, TRI_TABLE):
        failures.append(f"{TRI_TABLE} missing")
    posts = _count(conn, "posts")
    fts_rows = _count(conn, f"{FTS_TABLE}_docsize")
    tri_rows = _count(conn, f"{TRI_TABLE}_docsize")
    if posts >= 0 and fts_rows >= 0 and posts != fts_rows:
        failures.append(
            f"{FTS_TABLE} holds {fts_rows} rows, posts holds {posts}")
    if posts >= 0 and tri_rows >= 0 and posts != tri_rows:
        failures.append(
            f"{TRI_TABLE} holds {tri_rows} rows, posts holds {posts}")
    if _tri_shape_stale(conn):
        failures.append(
            f"{TRI_TABLE} indexes {sorted(_tri_columns(conn))}, not "
            f"{sorted(TRI_COLUMNS)} — rebuild")
    for trigger in TRIGGERS:
        present = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='trigger' AND name = ?",
            (trigger,)).fetchone() is not None
        if not present:
            failures.append(f"trigger {trigger} missing")
    if not failures and posts > 0:
        misses, sampled = _sample_tokens(conn, posts)
        if misses:
            failures.append(
                f"FTS cannot find a token from rows {misses[:6]}"
                + (f" (+{len(misses) - 6} more)" if len(misses) > 6 else ""))
    return failures


#: Rows `verify_fts` reads a token out of — spread across the id
#: range plus the newest, because the failure this looks for (a
#: trigger that stopped firing) is not clustered.
_SAMPLE_ROWS = 25


def _sample_tokens(conn, posts: int) -> tuple[list[int], int]:
    """(row ids whose token is missing from the index, rows sampled)."""
    if posts <= 0:
        return [], 0
    rows = conn.execute(
        "SELECT id, clean_title FROM posts"
        " WHERE clean_title IS NOT NULL AND length(clean_title) > 4"
        " ORDER BY id").fetchall()
    if not rows:
        return [], 0
    step = max(len(rows) // _SAMPLE_ROWS, 1)
    picked = rows[::step][:_SAMPLE_ROWS]
    newest = conn.execute(
        "SELECT id, clean_title FROM posts"
        " WHERE clean_title IS NOT NULL AND length(clean_title) > 4"
        " ORDER BY id DESC LIMIT 10").fetchall()
    seen, misses, sampled = set(), [], 0
    for row in list(picked) + list(newest):
        pid = int(row[0])
        if pid in seen:
            continue
        seen.add(pid)
        sampled += 1
        words = re.findall(r"[A-Za-z]{4,}", str(row[1] or ""))
        if not words:
            continue
        try:
            hit = conn.execute(
                f"SELECT rowid FROM {FTS_TABLE} WHERE {FTS_TABLE} MATCH ?",
                (f'"{words[0]}"',)).fetchone()
        except sqlite3.Error:
            misses.append(pid)
            continue
        if hit is None:
            misses.append(pid)
    return misses, sampled
