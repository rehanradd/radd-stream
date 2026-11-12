"""Did you mean: surface the correction a forgiving search already made.

Gap A4: the v1 omnibox fuzzy fallback silently returned corrected
results with `"fuzzy": True` and never told the viewer what it corrected
— a typo'd query looked like it had simply found nothing relevant, and
there was nothing to tap to see the corrected query's results. This
module turns the fuzzy machinery's output into the one string the UI
shows ("Did you mean: <corrected query>?") plus the corrected post ids
the caller serves when the viewer taps it.

The correction itself is NOT rebuilt here: `search_fuzzy` already finds
the candidate titles (3-gram pass, then true edit distance ≤ 1). This
module only asks it, per token, which title word a query token most
likely meant, and rebuilds the query from those words. A token with no
close title word is left exactly as typed — a correction is only ever
offered for the tokens the catalog can vouch for.

The candidate pass is the trigram FTS5 index (`fts_posts_tri`) when it
exists — 15–52 ms against the LIKE-gram scan's 903–1,424 ms (p95
5.3 s) — with the LIKE scan kept as the fallback for a database the
migration has not built the index on yet. Either way the true check
is in Python, so a shared gram never smuggles in a title that is
two edits away. The check is Damerau-Levenshtein ≤ 1, not plain
Levenshtein: a transposition (`inceptoin` → `inception`) is one edit.
And an ambiguous correction (`salar` → `salary` vs `salaar`, both one
edit away) is ranked by exact-title evidence: a candidate that IS a
whole title (`Salaar`) beats one that is only a word inside a longer
title (`Salary Man`).
"""

from __future__ import annotations

import re
import sqlite3

import fts_posts
import redact
import search_fuzzy

#: A token shorter than this is never corrected — "it", "up", "go" are
#: one edit from too many title words to mean anything.
_MIN_TOKEN_LEN = 4


def _query_tokens(query: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", (query or "").lower()) if t]


def _trigram_rows(conn, grams, limit):
    """Candidate rows via the trigram index, or None when it cannot answer.

    The same (clean_title, prints, mirrors) rows `_candidate_rows`
    returns, in trigram-rank order (rows sharing the most query
    trigrams first — the LIKE path orders by gram-score for the same
    reason: the true title word must survive a bounded window). The
    adult clause applies here too, so a suggestion never names a
    title the public surface hides. None means "no trigram index":
    the caller falls back to the LIKE-gram scan. An empty list means
    the index answered and found no candidate.
    """
    ids = fts_posts.trigram_candidate_ids(
        conn, fts_posts.trigram_match(grams), limit)
    if ids is None:
        return None
    if not ids:
        return []
    placeholders = ", ".join("?" for _ in ids)
    fetched = None
    for with_evidence in (True, False):
        try:
            if with_evidence:
                select = ("SELECT p.id, p.clean_title,"
                          " COUNT(DISTINCT r.id) AS rc,"
                          " COUNT(DISTINCT s.id) AS sc"
                          " FROM posts p"
                          " LEFT JOIN releases r ON r.post_id = p.id"
                          " LEFT JOIN download_sources s"
                          " ON s.release_id = r.id")
                group = " GROUP BY p.id"
            else:
                select = ("SELECT p.id, p.clean_title, 0 AS rc, 0 AS sc"
                          " FROM posts p")
                group = ""
            fetched = conn.execute(
                f"{select} WHERE {redact.adult_clause('p')}"
                f" AND p.id IN ({placeholders}){group}",
                ids).fetchall()
            break
        except sqlite3.OperationalError:
            if not with_evidence:
                return None
    order = {pid: i for i, pid in enumerate(ids)}
    fetched.sort(key=lambda row: order.get(int(row[0]), len(ids)))
    return [(row[1], row[2], row[3]) for row in fetched]


def _candidate_rows(conn, like_sql, score_sql, patterns, limit, *,
                    evidence):
    """Gram-matching posts, newest within a gram-score tie.

    With `evidence`, each row also carries its prints + mirrors
    (releases + sources) so an exact-but-obscure title word can be
    weighed against a popular near-miss. Without it the query touches
    `posts` alone — for a v2-only fixture with no releases table.
    """
    if evidence:
        select = ("SELECT p.clean_title,"
                  " COUNT(DISTINCT r.id) AS rc, COUNT(DISTINCT s.id) AS sc"
                  " FROM posts p"
                  " LEFT JOIN releases r ON r.post_id = p.id"
                  " LEFT JOIN download_sources s ON s.release_id = r.id")
        group = " GROUP BY p.id"
    else:
        select = "SELECT p.clean_title, 0 AS rc, 0 AS sc FROM posts p"
        group = ""
    return conn.execute(
        f"{select} WHERE {redact.adult_clause('p')}"
        f" AND ({like_sql}){group}"
        f" ORDER BY ({score_sql}) DESC, p.id DESC LIMIT ?",
        patterns + patterns + [int(limit)],
    ).fetchall()


def correct_token(conn, token: str, *, limit: int = 1000,
                  exclude: frozenset | None = None) -> str | None:
    """The title word `token` most likely meant, or None.

    One fuzzy pass over the catalog's title words (the same 3-gram +
    Damerau edit-distance machinery the omnibox fallback uses: the
    candidate pass is one trigram MATCH — or one LIKE scan where the
    trigram index does not exist yet — then the true check is
    `damerau_le1` in Python, so a transposition counts as one edit).
    A correction is only returned when it is a *different* word at
    Damerau distance ≤ 1 — an exact title word is already correct and
    needs no suggestion. The adult clause applies here too: a
    suggestion must never name a title the public surface hides.

    One exception to "exact needs no suggestion": a typed word that IS
    an exact title word but only on old, barely-printed rows, while a
    word one edit away is far better evidenced ("avtar" is a real old
    title; "avatar" is the film with the prints). Then the popular
    near-miss is offered — but only when its evidence (prints +
    mirrors, summed over the window's rows carrying the word) strictly
    exceeds the exact word's. A well-printed exact word never corrects.

    `exclude` is the poor-match path's word list: title words the
    exact search already served (`salar` → the served `salary` is one
    edit away too, and offering it back would be no correction at
    all). Excluded words are skipped, so the next closest word wins
    (`salaar`). On the miss path the set is empty and nothing changes.

    Ambiguity without an exclude list (`salar` → `salary` vs
    `salaar`, both one edit away) is ranked by exact-title evidence,
    not by window order: a candidate that IS a whole title (`Salaar`)
    beats one that is only a word inside a longer title (`Salary
    Man`); prints + mirrors break the remaining ties, then window
    order. The window already carries the bare titles, so the check
    costs no extra lookup.

    Recall: candidates are ordered by how many of the token's 3-grams
    the title shares, newest first within a tie — never by recency
    alone. The old `ORDER BY id DESC LIMIT 200` let the newest 200
    gram-matching rows crowd an old title out of the window, so
    "avengrs" never reached "Avengers". The window is wider too (the
    LIKE scan already reads the table; the limit only bounds rows
    fetched). The exact-word check runs over the whole window first,
    so a newer misspelling ("batmann") can never outrank the exact
    title word ("batman").
    """
    token = (token or "").lower()
    if len(token) < _MIN_TOKEN_LEN:
        return None
    grams = sorted(search_fuzzy.candidate_grams(token))
    if not grams:
        return None
    patterns = [f"%{gram}%" for gram in grams]
    like_sql = " OR ".join("lower(p.clean_title) LIKE ?" for _ in grams)
    # Parenthesise each term: in SQLite `+` binds tighter than
    # LIKE, so an unparenthesised `a LIKE ? + b LIKE ?` parses as a
    # chained comparison, not a sum of 0/1 matches — the score
    # would be meaningless and the ordering would fall back to
    # recency alone.
    score_sql = " + ".join("(lower(p.clean_title) LIKE ?)" for _ in grams)
    rows = _trigram_rows(conn, grams, limit)
    if rows is None:
        # No trigram index on this database (the migration has not
        # built it yet): the LIKE-gram scan answers instead, at the
        # old speed, with the same contract.
        try:
            rows = _candidate_rows(conn, like_sql, score_sql, patterns,
                                   limit, evidence=True)
        except sqlite3.OperationalError:
            # No releases/sources tables in this database (a v2-only
            # fixture): correct without evidence — an exact word never
            # corrects, a near-miss still does. A posts table without
            # the columns the clause needs still means no suggestion,
            # never a 500 from a missing table.
            try:
                rows = _candidate_rows(conn, like_sql, score_sql, patterns,
                                       limit, evidence=False)
            except sqlite3.OperationalError:
                return None
    words: list[str] = []
    evidence: dict[str, int] = {}
    bare_titles: set[str] = set()
    for row in rows:
        if isinstance(row, sqlite3.Row):
            title = row["clean_title"]
            weight = int(row["rc"] or 0) + int(row["sc"] or 0)
        else:
            title = row[0]
            weight = int(row[1] or 0) + int(row[2] or 0)
        title_tokens = search_fuzzy.tokenize(title or "")
        if len(title_tokens) == 1:
            bare_titles.add(title_tokens[0])
        for word in title_tokens:
            words.append(word)
            evidence[word] = evidence.get(word, 0) + weight
    # Exact first, across the whole window: a newer misspelling must
    # never outrank the exact title word — unless the near-miss is
    # better evidenced (see the docstring).
    if token in words:
        exact_weight = evidence.get(token, 0)
        best: str | None = None
        best_weight = exact_weight
        seen: set[str] = set()
        excluded = exclude or frozenset()
        for word in words:
            if word == token or word in seen or word in excluded:
                continue
            seen.add(word)
            if (evidence.get(word, 0) > best_weight
                    and search_fuzzy.damerau_le1(token, word)):
                best, best_weight = word, evidence[word]
        return best
    excluded = exclude or frozenset()
    candidates: list[str] = []
    seen: set[str] = set()
    for word in words:
        if word in seen or word in excluded:
            continue
        seen.add(word)
        if search_fuzzy.damerau_le1(token, word):
            candidates.append(word)
    if not candidates:
        return None
    # Ambiguity: a candidate that IS a whole title beats one that is
    # only a word inside a longer title; prints + mirrors break the
    # rest. The sort is stable, so window order breaks final ties.
    candidates.sort(key=lambda word: (word not in bare_titles,
                                      -evidence.get(word, 0)))
    return candidates[0]


def suggest_correction(conn, query: str, *, limit: int = 1000,
                       exclude: frozenset | None = None) -> dict | None:
    """The corrected query for `query`, or None when nothing corrects.

    Returns {"query": <corrected query>, "corrected_tokens": {<typed>:
    <corrected>, ...}} — the caller puts the corrected query in the
    "did_you_mean" field and serves `search` on it when tapped. Tokens
    that need no correction (exact title words, short words, names the
    catalog cannot vouch for) are left as typed, so a partial correction
    like "inceptoin 2" -> "inception 2" still offers the useful half.
    """
    tokens = _query_tokens(query)
    if not tokens:
        return None
    corrected: dict[str, str] = {}
    out_tokens: list[str] = []
    for token in tokens:
        fixed = correct_token(conn, token, limit=limit, exclude=exclude)
        if fixed is not None:
            corrected[token] = fixed
            out_tokens.append(fixed)
        else:
            out_tokens.append(token)
    if not corrected:
        return None
    return {"query": " ".join(out_tokens), "corrected_tokens": corrected}
