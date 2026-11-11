#!/usr/bin/env python3
"""Shared title / synopsis / rating cleaning — serve-time and ingest.

One module, stdlib only, no imports from the repo, so both the serve path
(`redact.project`, `viewer`) and the ingest path (`fast_fetch.save_scraped_data`)
can use the same rules. The ledger keeps the raw scraped text; these functions
decide what a viewer is shown and what a new row is filed under.

Three rules live here:

* ``clean_display_title`` — a scraped filename is not a title. ``"Salaar -
  Part 1 (2023) Multi Audios [Tel + Tam + Mal + Kan] NF WeB-DL"`` displays as
  ``"Salaar: Part 1"``; the technical tail becomes metadata, never the title.
  The cleaner is deliberately conservative: it only strips patterns the
  catalog actually writes (quality tags, sizes, ``Download`` prefixes, site
  suffixes, bracket groups), so a real title is never eaten.
* ``clean_synopsis`` — section markers such as a literal ``/PLOT`` line are
  ingest artifacts, never content. They are stripped at ingest and at serve
  time; a synopsis that was only a marker becomes empty.
* ``normalize_rating`` — a 0-100 value shown on a 0-10 scale (``"100"`` on
  ``Kesariya@100``) is divided by 10; anything else out of range is clamped
  to 10.0; missing or unparseable is None (the badge hides).
* ``group_work_rows`` — the search dedupe: rows of one work, filed under
  slightly different titles by different sites, collapse to one group.
"""

from __future__ import annotations

import html
import math
import re

# ── display title ─────────────────────────────────────────────────────────────

#: Tokens a trailing technical tail may consist of. Compared after lowercasing
#: and stripping non-alphanumerics, so ``WeB-DL`` matches ``webdl``.
_TAIL_TOKENS = frozenset({
    "480p", "720p", "1080p", "2160p", "4k", "2k", "hd", "sd", "uhd",
    "webdl", "web-dl", "bluray", "brrip", "hdrip", "hdtc", "hdtv", "hdts",
    "hevc", "x264", "x265", "h264", "h265", "10bit", "8bit",
    "esub", "esubs", "sub", "subs", "subbed", "dubbed", "dual", "audio",
    "audios", "multi", "org", "proper", "uncut", "unrated",
    "hindi", "tamil", "telugu", "malayalam", "kannada", "punjabi", "urdu",
    "english", "eng", "hin",
    "nf", "amzn", "prime", "zee5", "hotstar", "sonyliv", "netflix", "amazon",
    "full", "movie", "complete", "season", "series", "watch", "download",
    "official", "cam", "predvd", "dvdscr", "scr", "hdts",
    "dd51", "ddp51", "51ch", "51", "20", "atmos",
    "aac", "ac3", "dts", "dd", "eac3",
})

#: Site names a trailing suffix may name (the same slugs the public edge
#: already scrubs). Only used to cut a ``- <site>`` / ``| <site>`` tail.
_SITE_TOKENS = (
    "rogmovies", "vegamovies", "ssrmovies", "katmoviehd", "7starhd",
    "hdhub4u", "multimovies", "moviezguru", "rareanimes", "desicinemas",
    "9xmovies", "bolly4u", "filmyzilla", "10xflix", "hdtvb", "toonworld4all",
    "hindilinks4u", "movienestbd", "moviesdrive", "dramadog", "megacartoons",
)

_SIZE_RE = re.compile(r"^\d+(\.\d+)?\s?(gb|mb|kb)$", re.IGNORECASE)
_QUALITY_RE = re.compile(r"^\d+p$", re.IGNORECASE)
_PAREN_RE = re.compile(r"\([^)]*\)")
_BRACKET_RE = re.compile(r"\[[^\]]*\]")
_SITE_SUFFIX_RE = re.compile(
    r"\s*[-|–—]\s*(?:" + "|".join(_SITE_TOKENS) + r")\b.*$",
    re.IGNORECASE)
_LEADING_DOWNLOAD_RE = re.compile(r"^download\s+", re.IGNORECASE)


def _tail_token(token: str) -> str:
    return re.sub(r"[^a-z0-9]", "", token.lower())


def _is_tail_token(token: str) -> bool:
    norm = _tail_token(token)
    if not norm:
        return True
    if norm in _TAIL_TOKENS:
        return True
    if _SIZE_RE.match(token) or _QUALITY_RE.match(token):
        return True
    return False


def clean_display_title(title=None, clean_title=None) -> str:
    """The title a viewer is shown, from a stored row's two title columns.

    ``clean_title`` wins when it carries anything; ``title`` is the fallback.
    Returns ``""`` when nothing usable survives, so the caller can fall back
    to the raw value instead of rendering a blank.
    """
    text = str(clean_title or title or "")
    text = html.unescape(text).strip()
    if not text:
        return ""
    # A site suffix after a separator is never the title ("... | Rogmovies
    # Official..."). Keep the first segment; the rest is provenance.
    text = text.split("|")[0]
    text = _SITE_SUFFIX_RE.sub("", text)
    text = _LEADING_DOWNLOAD_RE.sub("", text).strip()
    # Bracket groups are technical tags ("[Tel + Tam + Mal + Kan]"), and a
    # parenthesised group is a year or an edition tag — neither belongs in a
    # display title (the year is its own field).
    text = _BRACKET_RE.sub(" ", text)
    text = _PAREN_RE.sub(" ", text)
    # "Salaar - 1 - Ceasefire" is one title in three pieces: fold it into
    # "Salaar: Part 1 – Ceasefire" instead of leaving the dashes. Any dash
    # counts here (hyphen, en dash, em dash) — the fold only fires on a part
    # number, so a subtitle dash elsewhere is untouched.
    parts = [p.strip() for p in re.split(r"\s+[-–—]\s+", text)]
    if len(parts) >= 2 and parts[1].isdigit():
        text = parts[0] + ": Part " + parts[1]
        if len(parts) > 2:
            text += " – " + " – ".join(parts[2:])
    elif len(parts) >= 2 and parts[1][:1].isdigit():
        # "Title - 2 Guns ..." — a leading number is a part number, not a
        # separator; keep the colon form for consistency.
        text = parts[0] + ": " + " – ".join(parts[1:])
    # A stray unbalanced paren survives when a per-site cleaner already cut
    # its partner ("Salaar Cease Fire Part 1)"): no balanced group is left
    # to remove, so drop the orphan characters outright.
    text = text.replace("(", "").replace(")", "")
    # Strip the trailing technical tail, one token at a time ("... NF WeB-DL
    # 480p [700MB]" is already bracket-stripped; "Multi Audios" goes here).
    tokens = text.split()
    while tokens and _is_tail_token(tokens[-1]):
        tokens.pop()
    text = " ".join(tokens)
    # A " - " that survived above separates the title from a subtitle only
    # when the tail starts with Part/Chapter/Vol ("Salaar - Part 1" reads as
    # "Salaar: Part 1"); anything else after a dash is a tag that was not
    # caught above ("Title - Hindi Dubbed").
    if " - " in text:
        head, _, tail = text.partition(" - ")
        if re.match(r"(?i)^(part|chapter|vol\.?|volume|episode|season)\b",
                    tail.strip()):
            text = head + ": " + tail
        else:
            text = head
    text = re.sub(r"\s{2,}", " ", text).strip(" \t-–—|·:,>&")
    text = re.sub(r"^[:·\-–—\s]+", "", text)
    return text.strip()


# ── synopsis ──────────────────────────────────────────────────────────────────

#: A whole line that is a section marker, never content ("/PLOT", "/PLOT:").
_MARKER_LINE_RE = re.compile(r"^\s*/[A-Za-z][A-Za-z0-9 _\-]*:?\s*$")
#: A marker heading a line of real text ("/PLOT: The story ...").
_LEADING_MARKER_RE = re.compile(r"^\s*/[A-Za-z][A-Za-z0-9 _\-]*:\s+")


def clean_synopsis(text) -> str:
    """A synopsis with section-marker lines removed.

    A marker-only synopsis (the 6,549 live rows whose synopsis is literally
    ``"/PLOT:"``) becomes ``""`` — the UI shows nothing rather than a stray
    marker. Real text survives untouched, including a leading marker on a
    line that also carries the plot.
    """
    if text is None:
        return ""
    out_lines = []
    for line in str(text).splitlines():
        if _MARKER_LINE_RE.match(line):
            continue
        line = _LEADING_MARKER_RE.sub("", line)
        out_lines.append(line)
    out = "\n".join(out_lines)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


# ── rating ────────────────────────────────────────────────────────────────────

def normalize_rating(value) -> str | None:
    """A one-decimal 0–10 rating string, or None for anything unshowable.

    ``"100"`` (a 0–100 value, as stored on ``Kesariya@100``) becomes
    ``"10.0"``; ``"25"`` becomes ``"2.5"``; anything above 100 clamps to
    ``"10.0"``; zero, negative, missing and unparseable become None, so the
    badge hides instead of showing a nonsense number. ``"7.8/10"`` labels
    are tolerated, like the backfill already does.
    """
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip().split("/", 1)[0].strip()
    if not text:
        return None
    try:
        rating = float(text)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(rating) or rating <= 0:
        return None
    if rating > 100:
        return "10.0"
    if rating > 10:
        rating = rating / 10.0
    return "%.1f" % rating


# ── work identity for search / rail dedupe ────────────────────────────────────

#: Tokens that carry no identity: technical tags, sizes, qualities, and the
#: words scrapers glue onto a headline. ``part`` is dropped but its number is
#: kept, so Part 1 and Part 2 stay different works.
_CORE_DROP = frozenset({
    "download", "watch", "full", "movie", "complete", "season", "series",
    "episode", "ep", "part", "chapter", "vol", "volume",
    "multi", "audio", "audios", "dual", "org", "proper", "uncut",
    "hindi", "tamil", "telugu", "malayalam", "kannada", "punjabi", "urdu",
    "english", "eng", "hin", "dubbed", "subbed", "esub", "esubs",
    "webdl", "web-dl", "web", "dl", "bluray", "brrip", "hdrip", "hdtc", "hevc",
    "x264", "x265", "h264", "h265", "nf", "amzn", "prime", "zee5",
    "480p", "720p", "1080p", "2160p", "4k", "hd", "sd", "uhd", "cam",
    "official", "s", "e",
})

#: Split spellings of one word, joined before tokenising.
_COMPOUNDS = (
    ("cease fire", "ceasefire"),
    ("cease-fire", "ceasefire"),
    ("spider man", "spiderman"),
    ("iron man", "ironman"),
)

_SERIES_TYPES = frozenset({"series", "complete_season", "ongoing_season"})


def work_family(content_type: str = "") -> str:
    """``"series"`` or ``"movie"`` — the two families never dedupe together."""
    return "series" if (content_type or "").strip().lower() in _SERIES_TYPES else "movie"


def _core_tokens(title: str) -> list[str]:
    text = html.unescape(title or "").casefold()
    for before, after in _COMPOUNDS:
        text = text.replace(before, after)
    text = _BRACKET_RE.sub(" ", text)
    text = _PAREN_RE.sub(" ", text)
    tokens = []
    for token in re.findall(r"\w+", text, flags=re.UNICODE):
        if token in _CORE_DROP:
            continue
        if re.fullmatch(r"\d{4}", token):
            continue  # a year token; the year is keyed separately
        if re.fullmatch(r"[se]\d+", token):
            continue  # S01 / E05 season-episode tags
        if re.fullmatch(r"\d+(gb|mb|kb)", token):
            continue  # a size tag
        if re.fullmatch(r"\d+p", token):
            continue  # a quality tag
        tokens.append(token)
    return sorted(set(tokens))


def work_core(title: str) -> str:
    """The sorted significant tokens of a title — the dedupe key's core."""
    return " ".join(_core_tokens(title))


def _year_of(value):
    try:
        year = int(value)
    except (TypeError, ValueError):
        return None
    return year if 1900 <= year <= 2100 else None


def group_work_rows(candidates):
    """Collapse candidate rows into one group per work.

    ``candidates`` are dicts with ``id``, ``title`` (or ``clean_title``),
    ``year``, ``content_type``, ``release_count`` and ``source_count``.
    Returns a list of groups (lists of candidate dicts), ordered by each
    group's best representative: most prints, then most mirrors, then newest
    id. Two rows are one work when their token cores match (one a subset of
    the other, so a bare ``"Salaar"`` folds into ``"Salaar: Part 1 –
    Ceasefire"``) in the same family and with years within one of each other
    — a remake twenty years later keeps its own group.
    """
    # Core buckets first: family + sorted-token core. A title with no
    # significant tokens is its own work — grouping it with anything else
    # would be a guess.
    buckets: dict[tuple, list] = {}
    blank: list[list] = []
    for cand in candidates:
        title = cand.get("clean_title") or cand.get("title") or ""
        core = tuple(_core_tokens(title))
        if not core:
            blank.append([cand])
            continue
        buckets.setdefault(
            (work_family(cand.get("content_type") or ""), core), []).append(cand)

    def years_of(group):
        return {_year_of(c.get("year")) for c in group} - {None}

    def years_compatible(left, right):
        ly, ry = years_of(left), years_of(right)
        if not ly or not ry:
            return True
        return any(abs(a - b) <= 1 for a in ly for b in ry)

    # Subset merge: a smaller core folds into the SMALLEST larger core that
    # contains it (same family), largest first, so "salaar" joins "1 ceasefire
    # salaar" rather than a junk superset — but "avatar" never joins "avatar
    # the way of water" (years differ).
    keys = sorted(buckets, key=lambda k: (-len(k[1]), k))
    merged_keys: list[tuple] = []
    for key in keys:
        family, core = key
        core_set = set(core)
        best = None
        best_diff = None
        for mkey in merged_keys:
            mfamily, mcore = mkey
            if mfamily != family or not core_set <= set(mcore):
                continue
            if not years_compatible(buckets[key], buckets[mkey]):
                continue
            diff = len(set(mcore) - core_set)
            if best_diff is None or diff < best_diff:
                best, best_diff = mkey, diff
        if best is not None:
            buckets[best].extend(buckets[key])
        else:
            merged_keys.append(key)
    groups = [list(buckets[k]) for k in merged_keys] + blank
    # Order groups by their best representative, best first.
    groups.sort(key=lambda g: (
        -int(representative(g).get("release_count") or 0),
        -int(representative(g).get("source_count") or 0),
        -int(representative(g).get("id") or 0)))
    return groups


def representative(group):
    """The row that stands for a deduped work: most prints, then mirrors."""
    return max(group, key=lambda c: (
        int(c.get("release_count") or 0),
        int(c.get("source_count") or 0),
        int(c.get("id") or 0)))
