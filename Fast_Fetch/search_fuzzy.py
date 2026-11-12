"""Typo-tolerant search fallback for /api/v1/posts.

Exact LIKE-substring search answers first and always. Only when it finds
nothing does this module run: a 3-gram candidate pass over clean_title
(one scan, capped at 200 rows), then a true edit-distance check in Python.
Nothing here invents a title — every row returned is a catalog row whose
title is one edit away from what the viewer typed, token by token.

The 3-gram prune is sound only for tokens of four letters or more: one edit
in a three-letter token can destroy every shared gram ("abc" vs "axc"), so
shorter tokens never enter the fuzzy pass — they keep the exact answer.
"""

import re

_TOKEN_RE = re.compile(r"[a-z0-9]+")
MAX_QUERY_TOKENS = 3
MIN_FUZZY_TOKEN_LEN = 4
MAX_TOKEN_LEN = 20
CANDIDATE_LIMIT = 200


def tokenize(text):
    """Lowercase alphanumeric tokens; punctuation and spaces are separators."""
    return _TOKEN_RE.findall((text or "").lower())


def edit_distance_le1(a, b):
    """True when the Levenshtein distance between a and b is at most 1.

    A single-row dynamic program with early exit: any row whose cheapest
    entry already exceeds 1 proves the distance is over 1, so the rest of
    the table is never built.
    """
    if a == b:
        return True
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    if la > lb:
        a, b = b, a
        la, lb = lb, la
    prev = list(range(lb + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * lb
        row_min = cur[0]
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            row_min = min(row_min, cur[j])
        if row_min > 1:
            return False
        prev = cur
    return prev[lb] <= 1


def damerau_le1(a, b):
    """True when the Damerau-Levenshtein distance between a and b is at most 1.

    Levenshtein ≤ 1, or one adjacent transposition: `inceptoin` is one
    transposition from `inception`, so it is one Damerau edit (and two
    Levenshtein edits, which is why `edit_distance_le1` rejects it).
    Transpositions are one of the most common typo types, so the
    correction check uses this and not plain Levenshtein. For a
    distance of ≤ 1 the restricted form (one transposition, checked
    directly) and full Damerau-Levenshtein agree.
    """
    if edit_distance_le1(a, b):
        return True
    if len(a) != len(b):
        return False
    diffs = [i for i, (ca, cb) in enumerate(zip(a, b)) if ca != cb]
    return (len(diffs) == 2 and diffs[1] == diffs[0] + 1
            and a[diffs[0]] == b[diffs[1]] and a[diffs[1]] == b[diffs[0]])


def fuzzy_match(query_tokens, title_tokens):
    """Every query token must match some title token within one edit.

    One edit in the Damerau sense: a transposition counts, so
    `inceptoin` matches `inception` while `avngrzx` still matches
    nothing two edits away.
    """
    if not query_tokens:
        return False
    for qt in query_tokens:
        if not any(damerau_le1(qt, tt) for tt in title_tokens):
            return False
    return True


def candidate_grams(token):
    """3-grams of one token. A title token one edit away from a token of
    four or more letters always shares at least one of these."""
    if len(token) < 3:
        return []
    return [token[i:i + 3] for i in range(len(token) - 2)]


def fuzzy_tokens(query):
    """The query tokens the fuzzy pass may use, or [] when the query cannot
    be fuzzed: empty, too many tokens, a token too short to prune, or a
    token too long to be a typo."""
    tokens = tokenize(query)[:MAX_QUERY_TOKENS]
    if not tokens:
        return []
    if len(tokenize(query)) > MAX_QUERY_TOKENS:
        return []
    for token in tokens:
        if len(token) < MIN_FUZZY_TOKEN_LEN or len(token) > MAX_TOKEN_LEN:
            return []
    return tokens
