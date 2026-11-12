"""Work-centric grouping for the v1 API (`/api/v1/works`).

One movie/series is one work; the ledger stores one POST per site copy,
so the same film can arrive as ten posts (`Salaar`: ten posts, eight
distinct `cat_works` keys — the projection inherits the fragmentation,
so it cannot be the grouping authority either). This module groups
posts into works at READ time, from the post rows themselves, by fuzzy
title + year — never by `imdb_id`/`tmdb_id` alone, because 85% of posts
carry neither.

The pieces, in order:

* `work_title_tokens` / `work_key_for_post` — the tier-1 key: ids when
  present, else `family:normalized-title:year-or-ny`. Edition words
  (quality, format, audio, source) are stripped from the title, never
  from the ledger: describing a cut is not describing a work.
* `group_posts` — tier-1 keys, then a tier-2 union-find that folds
  near-identical titles (one title a token-prefix of the other, or
  token Jaccard >= 0.6) within the same family and compatible years.
* `parse_season` / `parse_episode` / `format_season` /
  `format_episode` — one format for both (`S01` / `E01`); the ledger
  stores `1` and `S01`, `1` and `E01`, side by side.
* `build_seasons` — the episode list of a work with gaps marked:
  `available`, `missing`, or `in_pack` (a season pack may contain the
  episode; unknowable, so never claimed as missing).
* `language_buckets` / `language_sql` — the messy `posts.language`
  values (`Hindi` vs `["Hindi"]` vs `hindi`, `Hindi + English`,
  `Tel + Tam`) normalised into clean buckets: one per known language,
  plus `dual` (>= 2 languages), `multi` (>= 3) and `unknown`.
* `is_poor_match` / `STOPWORDS` — the search-quality helpers the
  posts and works list routes share: when the exact search returns
  rows that match no query token exactly, the typo correction is
  surfaced instead of silently serving the wrong thing; a single-token
  stopword matches whole words only.

Stdlib only. No DB writes, no imports from `viewer` (the route layer
imports this, never the reverse). The adult decision is the caller's,
through the `adult_agrees` checker `group_posts` takes: a flagged
member hides the work only when the fold's corroboration gate agrees
(`fast_fetch.adult_rule_agrees` — the flag re-derived from the row's
own texts). A flagged member that does not corroborate is excluded
from the work but does not hide it; with no checker the strict
default applies and any flagged member hides the group.
"""

from __future__ import annotations

import datetime
import json
import re

import catalog_v2

# ── title normalisation ──────────────────────────────────────────────────────

#: Words that describe a PRINT, never the work: quality, container, codec,
#: audio, source, or edition. Stripped from the grouping title only, at
#: token position >= 1 — the first token is the work's own name
#: ("Hindi Medium", "English Vinglish" keep their first word). "uncut" /
#: "unrated" sit here because they are edition labels, the same reason
#: they were removed from the adult patterns: a cut is not an audience.
EDITION_TOKENS = frozenset({
    # quality / container / codec
    "480p", "720p", "1080p", "2160p", "4k", "hd", "sd", "uhd", "hdr",
    "web-dl", "webdl", "web", "dl", "bluray", "blu-ray", "brrip", "hdrip",
    "hdtv", "dvdrip", "dvdscr", "cam", "hdcam", "ts", "tc", "predvd",
    "scr", "r5", "hevc", "x264", "x265", "10bit", "8bit", "aac", "dts",
    "dd5", "1ch", "2ch", "5ch", "6ch", "7ch", "proper", "repack",
    "imax", "hq", "lcr", "amzn", "nf", "webrip",
    # audio / language-of-print
    "multi", "audios", "audio", "dubbed", "dub", "org", "esub", "sub",
    "subbed", "dual", "hindi", "english", "tamil", "telugu", "malayalam",
    "kannada", "punjabi", "urdu", "bengali", "marathi", "gujarati",
    "tel", "tam", "mal", "kan", "hin", "eng", "urd", "pun", "ben",
    "mar", "guj", "russian", "chinese", "korean", "turkish", "japanese",
    # edition / source
    "uncut", "unrated", "extended", "remastered", "remaster", "restored",
    "restoration", "theatrical", "fanedit", "fansub", "cut", "directors",
    "untrimmed", "complete", "pack", "batch", "season", "episode",
    "download", "free", "watch", "online", "full", "movie",
})

#: A 4-digit year is a filing detail, not a title word ("Salaar (2023)").
_YEAR_RE = re.compile(r"^(19|20)\d{2}$")
#: `S01` / `E01` / `S1` tokens inside a title reduce to their number.
_SEASON_TOKEN_RE = re.compile(r"^s(\d{1,3})$")
_EPISODE_TOKEN_RE = re.compile(r"^e(\d{1,3})$")


def work_title_tokens(title: str) -> list[str]:
    """The grouping tokens of a title: normalised, edition-stripped.

    `catalog_v2.normalize_title` already strips bracketed/paren content
    (so `[S01E08 Added]` never reaches a key) and punctuation. On top
    of that: drop 4-digit years, drop the word `part` before a number
    (`Salaar Part 1` ≡ `Salaar 1`), reduce `S01`/`E01` tokens to their
    number, and drop edition tokens at position >= 1.
    """
    raw = (catalog_v2.normalize_title(title) or "").split()
    out: list[str] = []
    for index, token in enumerate(raw):
        if _YEAR_RE.match(token):
            continue
        if token == "part" and index + 1 < len(raw) and raw[index + 1].isdigit():
            continue
        season = _SEASON_TOKEN_RE.match(token)
        if season:
            out.append(str(int(season.group(1))))
            continue
        episode = _EPISODE_TOKEN_RE.match(token)
        if episode:
            out.append(str(int(episode.group(1))))
            continue
        if index >= 1 and token in EDITION_TOKENS:
            continue
        out.append(token)
    return out


def _clamped_year(year) -> str:
    """The grouping year: a real year, else `ny` (same clamp the list
    route orders by — 2099/2077/2067 are swallowed numbers, not years)."""
    try:
        number = int(year)
    except (TypeError, ValueError):
        return "ny"
    if 1900 <= number <= datetime.date.today().year + 1:
        return str(number)
    return "ny"


def _row_parts(row) -> tuple[str, str, tuple[str, ...], str]:
    """(tier-1 key, family, title tokens, clamped year) of one post row.

    The key is the exact identity (ids when present); the family /
    tokens / year are the row's own, NOT parsed back out of the key —
    an id-keyed row (`imdb:tt13927994`) carries no title in its key,
    and tier-2 merging needs the real title to fold it with its
    id-less twins (Salaar: 1 of 9 posts carries an id; without this
    the id'd copy could never merge with the other eight)."""
    get = row.get if isinstance(row, dict) else lambda k, d=None: row[k]
    try:
        imdb_id = (get("imdb_id") or "").strip()
    except (KeyError, IndexError, TypeError):
        imdb_id = ""
    try:
        tmdb_id = get("tmdb_id")
    except (KeyError, IndexError, TypeError):
        tmdb_id = None
    title = get("clean_title") or get("title") or ""
    try:
        content_type = get("content_type") or "movie"
    except (KeyError, IndexError, TypeError):
        content_type = "movie"
    try:
        is_animated = int(get("is_animated") or 0)
    except (KeyError, IndexError, TypeError, ValueError):
        is_animated = 0
    work_type = catalog_v2.work_type_for(content_type, is_animated, title)
    family = catalog_v2.work_family(work_type)
    tokens = tuple(work_title_tokens(title)) or ("unknown",)
    year = _clamped_year(get("year"))
    if imdb_id:
        key = f"imdb:{imdb_id}"
    elif tmdb_id not in (None, "", 0):
        key = f"tmdb:{tmdb_id}"
    else:
        norm = " ".join(tokens)
        key = f"{family}:{norm}:{year}"
    return key, family, tokens, year


def work_key_for_post(row) -> str:
    """The tier-1 key of one post row (dict or sqlite Row).

    Ids win when present — the strongest signal there is. Otherwise
    family + normalized title + year, the same shape
    `catalog_v2.work_key_for` mints, so a key a caller already holds
    still resolves. Family never merges across: a movie and a series
    that share a title are two works.
    """
    return _row_parts(row)[0]


def _years_compatible(year_a: str, year_b: str) -> bool:
    """Equal, one unknown, or within one year (scrapers disagree by a
    year on the same film: Salaar filed as both 2023 and 2024)."""
    if year_a == year_b or "ny" in (year_a, year_b):
        return True
    try:
        return abs(int(year_a) - int(year_b)) <= 1
    except ValueError:
        return False


#: Tokens that mark a SEQUEL, never the same film: a bare number >= 2
#: or its word form, in the part of the title that differs. `dune` ⊂
#: `dune part two` must not merge (different films, 2021 vs 2024 —
#: the year rule blocks it too, but the guard is what holds when a
#: sequel lands the next year). `salaar` ⊂ `salaar 1 ceasefire` is
#: fine: `1` is not a sequel marker. `22`/`2001` are not in the set —
#: they are title words, not part numbers.
_SEQUEL_TOKENS = frozenset({
    "2", "3", "4", "5", "6", "7", "8", "9",
    "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
})


def _titles_mergeable(tokens_a: tuple[str, ...], tokens_b: tuple[str, ...]) -> bool:
    """One title is a token-prefix of the other, or they share >= 60%
    of their tokens. `salaar` ⊂ `salaar 1 ceasefire`; `salaar 1
    ceasefire` vs `salaar cease fire` is the known miss (Jaccard 0.2,
    no bare title to hub them) — see the design note, §2. Either way
    a sequel marker in the differing tokens vetoes the merge: `john
    wick` never folds `john wick chapter 2`."""
    if not tokens_a or not tokens_b:
        return False
    if (set(tokens_a) ^ set(tokens_b)) & _SEQUEL_TOKENS:
        return False
    short, long_ = (tokens_a, tokens_b) if len(tokens_a) <= len(tokens_b) else (tokens_b, tokens_a)
    if tuple(long_[:len(short)]) == tuple(short):
        return True
    set_a, set_b = set(tokens_a), set(tokens_b)
    union = set_a | set_b
    if not union:
        return False
    return len(set_a & set_b) / len(union) >= 0.6


def group_posts(rows, adult_agrees=None) -> list[dict]:
    """Group post rows into works.

    Input rows carry at least: id, clean_title, title, year,
    content_type, is_animated, imdb_id, tmdb_id, is_18_plus.
    Output, one dict per work, in no particular order (the caller
    sorts): `work_key` (the tier-1 key of the representative post),
    `family`, `title_tokens`, `year` (representative's clamped year),
    `post_ids` (the SERVABLE members, ascending — flagged members are
    never servable), `flagged_ids` (flagged members, ascending),
    `post_count` (servable members), `work_id` (the minimum servable
    post id — the work's stable numeric identity for `/works/<id>`,
    None when no member is servable), and `flagged` (True when the
    work must be hidden whole).

    The adult rule is the fold's corroboration gate, not a raw MAX:
    `adult_agrees` is a callable(row) -> bool (the caller passes
    `fast_fetch.adult_rule_agrees`, which re-derives the flag from the
    row's own texts). A flagged member hides the work only when the
    gate agrees — a flag no rule can reproduce is a review candidate,
    and folding across it hid 407 mainstream works (measured
    2026-10-30). A flagged member that does not corroborate is
    excluded from the work but does not hide it: Salaar carries one
    such twin live, and the work must still answer. With no checker
    supplied the strict default applies: any flagged member hides
    the group. Which member post supplies the displayed fields
    (poster, rating, …) is the caller's choice, not grouping's:
    grouping only names the members.
    """
    groups: dict[str, dict] = {}
    for row in rows:
        key, family, tokens, year = _row_parts(row)
        group = groups.get(key)
        if group is None:
            group = {"work_key": key, "family": family, "title_tokens": tokens,
                     "year": year, "post_ids": [], "flagged_ids": [],
                     "flagged": False}
            groups[key] = group
        if row["is_18_plus"]:
            group["flagged_ids"].append(int(row["id"]))
            if adult_agrees is None or adult_agrees(row):
                group["flagged"] = True
        else:
            group["post_ids"].append(int(row["id"]))
    # Tier 2: union-find over tier-1 groups. Same family, compatible
    # years, mergeable titles. The naive double loop is O(G^2) over
    # ~200k groups and never finishes; instead the groups are sorted by
    # (family, title tokens) and each group is compared with the next
    # WINDOW groups only. Mergeable titles sort next to each other — a
    # prefix sorts immediately before its extensions, and a near-duplicate
    # differs by a token or two — and union-find transitivity chains the
    # rest (`salaar` hubs `salaar 1 ceasefire` and `salaar cease fire`
    # together even though the two extensions never meet directly).
    # WINDOW bounds the work to O(G * WINDOW).
    WINDOW = 10
    ordered = sorted(groups.values(),
                     key=lambda g: (g["family"], g["title_tokens"]))
    parent = {id(g): g for g in ordered}

    def find(group: dict) -> dict:
        root = group
        while parent[id(root)] is not root:
            root = parent[id(root)]
        while parent[id(group)] is not root:
            parent[id(group)], group = root, parent[id(group)]
        return root

    for index, group_a in enumerate(ordered):
        for group_b in ordered[index + 1:index + 1 + WINDOW]:
            if group_b["family"] != group_a["family"]:
                break
            if not _years_compatible(group_a["year"], group_b["year"]):
                continue
            if not _titles_mergeable(group_a["title_tokens"], group_b["title_tokens"]):
                continue
            root_a, root_b = find(group_a), find(group_b)
            if root_a is not root_b:
                parent[id(root_b)] = root_a
    merged: dict[int, dict] = {}
    for group in ordered:
        root = find(group)
        target = merged.get(id(root))
        if target is None:
            target = dict(root)
            target["post_ids"] = list(root["post_ids"])
            target["flagged_ids"] = list(root["flagged_ids"])
            merged[id(root)] = target
            continue
        target["post_ids"].extend(group["post_ids"])
        target["flagged_ids"].extend(group["flagged_ids"])
        target["flagged"] = target["flagged"] or group["flagged"]
        # The merged work keeps the earliest (smallest-id) tier-1 key as
        # its key: deterministic, and the bare title usually owns it.
        if group["work_key"] < target["work_key"]:
            target["work_key"] = group["work_key"]
            target["title_tokens"] = group["title_tokens"]
            target["year"] = group["year"]
    out = []
    for group in merged.values():
        group["post_ids"] = sorted(set(group["post_ids"]))
        group["flagged_ids"] = sorted(set(group["flagged_ids"]))
        group["post_count"] = len(group["post_ids"])
        group["work_id"] = group["post_ids"][0] if group["post_ids"] else None
        out.append(group)
    return out


# ── season / episode normalisation ───────────────────────────────────────────

_SEASON_VALUE_RE = re.compile(r"^(?:s|season\s*)?(\d{1,3})$", re.IGNORECASE)
_EPISODE_VALUE_RE = re.compile(r"^(?:e|episode\s*)?(\d{1,3})$", re.IGNORECASE)


def parse_season(value) -> int | None:
    """`1`, `S01`, `S1`, `Season 1` → 1. Anything else → None."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    match = _SEASON_VALUE_RE.match(text)
    if not match:
        return None
    number = int(match.group(1))
    return number if 1 <= number <= 999 else None


#: Episode values that name a pack, not an episode. 10,525 releases
#: carry the literal `Batch` (data baseline 2026-11-12); `complete` /
#: `pack` / `all` / `full` are the same shape. They parse to None, so
#: `build_seasons` treats the release as a pack and its season's
#: unnamed episodes read `in_pack`, never `missing` and never a
#: phantom episode number.
_BATCH_EPISODE_VALUES = frozenset({"batch", "complete", "pack", "all", "full"})


def parse_episode(value) -> int | None:
    """`1`, `E01`, `E1`, `Episode 1` → 1. Anything else → None —
    including the pack words above, which are never an episode."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.casefold() in _BATCH_EPISODE_VALUES:
        return None
    match = _EPISODE_VALUE_RE.match(text)
    if not match:
        return None
    number = int(match.group(1))
    return number if 1 <= number <= 999 else None


def format_season(number: int) -> str:
    return "S%02d" % int(number)


def format_episode(number: int) -> str:
    return "E%02d" % int(number)


_ONGOING_TITLE_RE = re.compile(r"\[\s*S\d+\s*E\d+[^\]]*added[^\]]*\]", re.IGNORECASE)


def title_marks_ongoing(title: str) -> bool:
    """An ongoing-season title embeds `[S01E08 Added]` and changes on
    every re-scrape — the marker, not the title, is the signal."""
    return bool(_ONGOING_TITLE_RE.search(title or ""))


def build_seasons(release_rows) -> tuple[list[dict], int | None]:
    """The episode list of a work, from its releases' season/episode
    columns, with gaps marked.

    Each release row carries season, episode, created_at. Returns
    (seasons, latest_episode_added_at): seasons is a list of
    {"season": "S01", "episodes": [{"episode": "E01", "status":
    "available"|"missing"|"in_pack"}]}; a season with a pack release
    (episode NULL, season set) marks its unnamed episodes `in_pack`,
    never `missing` — the pack may contain them. The latest
    `created_at` over the releases is the new-episode signal the
    client diffs across polls (there is no snapshot table).
    Seasons are sorted ascending; episodes run 1..max in each season.
    """
    by_season: dict[int, set[int]] = {}
    packs: set[int] = set()
    latest = None
    for row in release_rows:
        get = row.get if isinstance(row, dict) else lambda k, d=None: row[k]
        try:
            created = get("created_at")
        except (KeyError, IndexError, TypeError):
            created = None
        if created:
            latest = created if latest is None else max(latest, created)
        season = parse_season(get("season"))
        if season is None:
            continue
        episode = parse_episode(get("episode"))
        if episode is None:
            packs.add(season)
            continue
        by_season.setdefault(season, set()).add(episode)
    seasons = []
    for season in sorted(set(by_season) | packs):
        numbers = by_season.get(season, set())
        top = max(numbers) if numbers else 0
        episodes = []
        for number in range(1, top + 1):
            if number in numbers:
                status = "available"
            elif season in packs:
                status = "in_pack"
            else:
                status = "missing"
            episodes.append({"episode": format_episode(number), "status": status})
        seasons.append({"season": format_season(season), "episodes": episodes})
    return seasons, latest


# ── language buckets ─────────────────────────────────────────────────────────

#: Canonical language token -> spellings that mean it (full words and
#: the abbreviations scrapers file: `Tel + Tam + Mal + Kan`). Matching
#: is token-exact in Python, never substring — `hin` must not match
#: inside `chinese`.
LANGUAGE_ALIASES = {
    "hindi": ("hindi", "hin"),
    "english": ("english", "eng"),
    "urdu": ("urdu", "urd"),
    "tamil": ("tamil", "tam"),
    "telugu": ("telugu", "tel"),
    "malayalam": ("malayalam", "mal"),
    "kannada": ("kannada", "kan"),
    "punjabi": ("punjabi", "pun"),
    "bengali": ("bengali", "ben"),
    "marathi": ("marathi", "mar"),
    "gujarati": ("gujarati", "guj"),
    "russian": ("russian", "rus"),
    "chinese": ("chinese", "chi", "mandarin", "cantonese"),
    "korean": ("korean", "kor"),
    "turkish": ("turkish", "tur"),
    "japanese": ("japanese", "jap"),
    "spanish": ("spanish", "spa"),
    "french": ("french", "fre"),
    "arabic": ("arabic", "ara"),
    "persian": ("persian", "per", "farsi"),
    "portuguese": ("portuguese", "por"),
    "thai": ("thai",),
    "indonesian": ("indonesian", "ind"),
    "vietnamese": ("vietnamese", "vie"),
}

_ALIAS_TO_CANONICAL = {alias: canon for canon, aliases in LANGUAGE_ALIASES.items()
                       for alias in aliases}

#: Tokens that are filing noise, not a language.
_LANGUAGE_NOISE = frozenset({
    "unknown", "none", "null", "n/a", "other", "-", "[]", "",
    "original", "audio", "org", "fan", "dubbed", "voice", "over",
    "dual", "multi", "esub",
})

_TOKEN_SPLIT_RE = re.compile(r"[^a-z]+")


def language_tokens(value) -> list[str]:
    """The canonical language tokens in a stored language value.

    Accepts a JSON array (`["Hindi"]`), a comma list, a `+`-joined
    string (`Hindi + English`), or a plain word. Abbreviations expand
    (`tel` → `telugu`); noise (`Unknown`, `Original Audio`, `[]`)
    yields nothing.
    """
    if value is None:
        return []
    text = str(value).strip()
    if not text or text == "[]":
        return []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            parsed = None
        if isinstance(parsed, list):
            items = [str(item) for item in parsed]
        else:
            items = [text]
    else:
        items = [text]
    out: list[str] = []
    for item in items:
        for piece in _TOKEN_SPLIT_RE.split(item.lower()):
            if not piece or piece in _LANGUAGE_NOISE:
                continue
            canonical = _ALIAS_TO_CANONICAL.get(piece)
            if canonical and canonical not in out:
                out.append(canonical)
    return out


def language_buckets(value) -> set[str]:
    """The buckets a stored language value belongs to: its languages,
    plus `dual` (>= 2), `multi` (>= 3), or `unknown` (none)."""
    tokens = language_tokens(value)
    buckets = set(tokens)
    if len(tokens) >= 2:
        buckets.add("dual")
    if len(tokens) >= 3:
        buckets.add("multi")
    if not tokens:
        buckets.add("unknown")
    return buckets


def language_sql(bucket: str):
    """The SQL predicate (fragment on alias `p`, params) for a bucket,
    or None when the value is not a bucket at all.

    Single languages match as substrings of the raw stored string —
    `["Hindi"]`, `Hindi`, `hindi` and `Hindi + English` all contain
    `hindi` — which is exactly the old `language=` LIKE, so a
    single-language chip keeps its rows. `dual` / `multi` count how
    many full-token languages the raw string names (>= 2 / >= 3);
    abbreviation-only rows (`Tel + Tam`) are undercounted in SQL and
    exact in Python — documented, not hidden. `unknown` is the
    complement: no known language token appears at all.
    """
    key = (bucket or "").strip().lower()
    if key in LANGUAGE_ALIASES:
        return (r"lower(p.language) LIKE ? ESCAPE '\'", ["%" + key + "%"])
    if key in ("dual", "multi"):
        threshold = 2 if key == "dual" else 3
        terms = " + ".join(
            "(CASE WHEN lower(p.language) LIKE ? ESCAPE '\\' THEN 1 ELSE 0 END)"
            for _ in LANGUAGE_ALIASES)
        params = ["%" + canon + "%" for canon in LANGUAGE_ALIASES]
        return (f"({terms}) >= ?", params + [threshold])
    if key == "unknown":
        terms = " + ".join(
            "(CASE WHEN lower(p.language) LIKE ? ESCAPE '\\' THEN 1 ELSE 0 END)"
            for _ in LANGUAGE_ALIASES)
        params = ["%" + canon + "%" for canon in LANGUAGE_ALIASES]
        return (f"({terms}) = 0", params)
    return None


# ── search quality ───────────────────────────────────────────────────────────

#: Words too common to mean anything as a substring: `the` matches
#: `other`, `together`, `them`. A query that IS one of these matches
#: whole words only.
STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for",
    "with", "by", "at", "from",
})


def is_whole_word_query(query: str) -> bool:
    """True for a single-token stopword, or a single token of <= 2
    letters (`it`, `up`, `go` are substrings of everything)."""
    tokens = [t for t in re.split(r"[^a-z0-9]+", (query or "").lower()) if t]
    return len(tokens) == 1 and (tokens[0] in STOPWORDS or len(tokens[0]) <= 2)


def whole_word_title_clause(query: str):
    """The SQL predicate (fragment on alias `p`, params) matching a
    whole word in the title fields: equal, leading, trailing, or
    surrounded by spaces. Cast names are excluded — a stopword in a
    cast list is junk, not a match."""
    token = (query or "").strip().lower()
    escaped = token.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    patterns = [token, token + " %", "% " + token, "% " + token + " %"]
    clause = " OR ".join(
        f"(lower(p.{col}) = ? OR lower(p.{col}) LIKE ? ESCAPE '\\'"
        f" OR lower(p.{col}) LIKE ? ESCAPE '\\'"
        f" OR lower(p.{col}) LIKE ? ESCAPE '\\')"
        for col in ("clean_title", "title", "slug"))
    params: list = []
    for _ in ("clean_title", "title", "slug"):
        params.extend([token,
                       escaped + " %", "% " + escaped, "% " + escaped + " %"])
    return "(" + clause + ")", params


def is_poor_match(query: str, result_titles) -> bool:
    """True when NO result title contains any query token exactly.
    `salar` against `Salary Man` is poor (the token is `salary`, not
    `salar`); `dune` against `Dune: Part Two` is good. A string prefix
    is deliberately NOT a good match — `salar` is a prefix of `salary`
    too, and that is exactly the wrong-title case the correction must
    surface for. Whether a correction exists is the caller's check:
    `sala` against `Salaar` is poor by this test as well, but no
    one-edit correction exists for it, so nothing is offered."""
    query = (query or "").strip().lower()
    if not query:
        return False
    query_tokens = [t for t in re.split(r"[^a-z0-9]+", query) if t]
    if not query_tokens:
        return False
    query_set = set(query_tokens)
    for title in result_titles:
        title_tokens = set(re.split(r"[^a-z0-9]+", (title or "").lower()))
        if query_set & title_tokens:
            return False
    return True
