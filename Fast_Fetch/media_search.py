#!/usr/bin/env python3
"""Match a video file the viewer is holding to a work in our catalog.

The question this answers is the one a phone can ask and a keyword search cannot:
"I have a 1 437-second, 1920x1080, Hindi/English file called roughly *Inception* —
which title is this?" A title search already exists (`/api/v1/posts?q=`); what did
not exist was a way to use the media facts as *evidence* rather than as extra words,
and an honest answer when the ledger cannot confirm one of them.

Every hint is therefore reported three ways, never as a bare score:
``matched_on`` (the ledger agrees), ``mismatched_on`` (the ledger holds a value and
it disagrees), ``unknown_on`` (we have nothing to compare against). Collapsing the
third into the first would rank a work above another purely because our row for it
is emptier.

A title is required, and that is a fact about the catalog rather than a limitation
of the code: 130 016 works, of which several thousand are ~120-minute 480p films.
Duration and resolution alone do not discriminate among them — they would rank the
whole ledger to say "here are 10 of possibly 10 000". So the endpoint says so
instead of burning the VM to produce a list that means nothing, and the app asks
for a title first.

**Why the query is shaped the way it is.** Until 2026-10-29 this module asked SQLite
for the matches, the print counts and the ranking in one statement:

    FROM posts p
    LEFT JOIN releases r ON r.post_id = p.id
    LEFT JOIN download_sources s ON s.release_id = r.id
    WHERE p.clean_title LIKE '%…%' OR p.title LIKE '%…%'
    GROUP BY p.id ORDER BY (release_count + source_count) DESC LIMIT ?

`EXPLAIN QUERY PLAN` against the 150 799-post catalog said `SCAN p`, both LEFT-JOINs
through a covering index, and three `USE TEMP B-TREE` — two for the `COUNT(DISTINCT …)`
and one for the `ORDER BY`. The LIKE cannot use an index (none exists on `clean_title`
or `title`), so all 150 799 posts were visited; the catalog holds 1 780 121 releases
and 4 073 865 download sources, so a common letter materialised on the order of four
million joined rows *before* `LIMIT` was consulted, and the popularity sort then
ordered every one of those groups. Measured live at the edge: `q=love` answered in
45 s, `q=a` never answered at all, and nginx's `proxy_read_timeout 30s` turned both
into a 504 behind a spinner. The `LIMIT` bounded the *response*, never the *work*.

So the work is bounded where the work actually is: candidates come from `posts` alone
and are capped before anything is joined, and the counts for that capped window are
read back through the two foreign-key indexes. Nothing here joins the catalog again.
Stdlib only, and it never opens a write transaction: the catalog is read as-is.
"""

from __future__ import annotations

import re

try:
    import redact
except ImportError:  # imported as part of the package from the repo root
    from Fast_Fetch import redact

#: A scraped runtime is a nominal broadcast length, not a file measurement: cut
#: versions, ad breaks and a rounding to whole minutes all move it. 10% was the
#: number in the original sketch and it is too tight for that kind of data.
DURATION_TOLERANCE = 0.15

#: How many candidates the ledger is asked for before the evidence is scored. The
#: ranking that matters happens here, over this window, not in SQL over 130k rows.
CANDIDATE_WINDOW = 200

#: A query shorter than this is not a query. One character matches nearly the whole
#: catalog, and "nearly the whole catalog, ranked" is the shape that cost 45 s and
#: then a 504. A search box is never legitimately used at one keystroke, so the
#: answer is an empty one plus a hint — no SQL at all, not a faster scan. The client
#: floor must match this value; see `ANDROID_INTEGRATION.md`.
MIN_QUERY_CHARS = 2

#: LIKE metacharacters are wildcards, so an unescaped `%` in a *user's* query is a
#: request to match everything: the same cliff as `q=a`, reached with one keystroke.
_ESCAPE_CHAR = "\\"

#: What a caller may call a rung, in the words the catalog actually stores. The
#: ladder is walked top-down, so a longer word never loses to a substring of it
#: ("uhd" is checked before the bare "hd" that lives inside it).
_HEIGHT_LADDER = (
    ("2160p", ("2160", "4k", "uhd")),
    ("1080p", ("1080", "fullhd", "full hd", "fhd")),
    ("720p", ("720", "hd")),
    ("480p", ("480", "sd", "dvdrip")),
)

#: "1920x1080" in a hint is the same claim as "1080p".
_DIMENSIONS_RE = re.compile(r"^\s*(\d{3,5})\s*[x×]\s*(\d{3,5})\s*$")


def normalize_resolution(value) -> str:
    """Reduce a stored or supplied rung to one of our four labels; '' if unknown."""
    text = str(value or "").strip().lower()
    if not text:
        return ""
    dims = _DIMENSIONS_RE.match(text)
    if dims:
        height = int(dims.group(2))
        for label, _ in _HEIGHT_LADDER:            # top of the ladder first
            if height >= int(label[:-1]) * 0.9:
                return label
        return ""
    squeezed = re.sub(r"[\s_\-]+", "", text)
    for label, aliases in _HEIGHT_LADDER:
        if any(re.sub(r"[\s_\-]+", "", a) in squeezed for a in aliases):
            return label
    return ""


def duration_matches(runtime_minutes, duration_s) -> "bool | None":
    """True/false when both sides are known, None when either is missing."""
    try:
        minutes = float(runtime_minutes)
        seconds = float(duration_s)
    except (TypeError, ValueError):
        return None
    if minutes <= 0 or seconds <= 0:
        return None
    expected = minutes * 60.0
    return abs(seconds - expected) <= expected * DURATION_TOLERANCE


def _escape_like(text: str) -> str:
    """Quote `%`, `_` and the escape character itself, so user text matches as text."""
    return (str(text).replace(_ESCAPE_CHAR, _ESCAPE_CHAR + _ESCAPE_CHAR)
            .replace("%", _ESCAPE_CHAR + "%")
            .replace("_", _ESCAPE_CHAR + "_"))


def _contains_pattern(text: str) -> str:
    return f"%{_escape_like(text)}%"


def _row_columns(full: bool) -> str:
    """The `posts` columns the projection and the evidence step need, in one list.

    Carried by the candidate scan itself, so the window is read once. A separate
    `WHERE p.id IN (…)` fetch costs one statement per search and buys nothing: the
    scan already touches exactly those rows.
    """
    provenance = ", p.source_site, p.url, p.slug" if full else ""
    return (f"p.id, p.clean_title, p.title, p.year, p.content_type, p.seasons,"
            f" p.imdb_rating, p.imdb_id, p.tmdb_id, p.genres, p.is_animated,"
            f" p.industry, p.country, p.language, p.poster_url, p.backdrop_urls"
            f"{provenance}")


def _candidates(conn, clean: str, window: int, full: bool) -> tuple:
    """One newest-first walk of `posts`, returning `(rows, tier)`.

    Only the `contains` test is in SQL, because that is the one that decides whether a
    row exists at all; the *strength* of the match (2 exact, 1 prefix, 0 contains) is
    computed in Python over the at-most-`window` rows that came back. Putting the tier
    in the SELECT list instead cost three LIKE/lower() evaluations per examined row —
    up to 150 799 of them — which measured slower than the statement this replaced for
    a whole-title query. The scan is one statement, `ORDER BY p.id DESC LIMIT ?` walks
    the rowid backwards so the plan is `SCAN p` with no temp B-tree at any size, and
    there is no join anywhere near it.

    The recall boundary is a fact and not an accident: candidates are the *newest*
    `window` matches, then ranked by title strength, evidence agreement and print
    count. A film that is popular but old can therefore be missed by a broad query that
    the old whole-catalog popularity sort would have surfaced — the price of bounding
    the work before the join instead of after it.
    """
    wanted = clean.lower()
    sql = (f"SELECT {_row_columns(full)} FROM posts p"
           f" WHERE {redact.adult_clause('p', keyed=True)}"
           f" AND (p.clean_title LIKE ? ESCAPE '\\' OR p.title LIKE ? ESCAPE '\\')"
           f" ORDER BY p.id DESC LIMIT ?")
    contains = _contains_pattern(clean)
    rows = conn.execute(sql, [contains, contains, window]).fetchall()
    tier: dict = {}
    for row in rows:
        pid = int(row["id"])
        title = str(row["clean_title"] or "").lower()
        if title == wanted:
            tier[pid] = 2
        elif title.startswith(wanted) or str(row["title"] or "").lower().startswith(wanted):
            tier[pid] = 1
        else:
            tier[pid] = 0
    return rows, tier


def _counts_for(conn, post_ids: list) -> dict:
    """Print and mirror counts for a *capped* id list, read back through the indexes.

    The same ranking signal the old `COUNT(DISTINCT …)` pair produced, computed after
    the candidate set was bounded instead of over the entire fan-out: one probe of
    `idx_releases_post` per candidate, one grouped pass over `idx_sources_rel` for the
    releases those candidates own. `COUNT(DISTINCT s.id)` counted the same thing,
    because a source row belongs to exactly one release — so no duplicate can reach a
    count by this route and no distinct is needed.
    """
    if not post_ids:
        return {}
    out: dict = {}
    marks = ",".join("?" * len(post_ids))
    for row in conn.execute(
            f"SELECT post_id, COUNT(*) FROM releases WHERE post_id IN ({marks})"
            f" GROUP BY post_id", post_ids):
        out[int(row[0])] = [int(row[1]), 0]
    for row in conn.execute(
            f"SELECT r.post_id, COUNT(*) FROM download_sources s"
            f" JOIN releases r ON r.id = s.release_id"
            f" WHERE r.post_id IN ({marks}) GROUP BY r.post_id", post_ids):
        out.setdefault(int(row[0]), [0, 0])[1] = int(row[1])
    return out


def _empty_evidence() -> dict:
    return {"runtime_minutes": None, "languages": set(), "resolutions": set()}


def _work_evidence(conn, post_ids: list) -> dict:
    """Runtime, rungs and audio languages the catalog holds for these posts.

    Reached through ``cat_work_sites.post_id`` — that column, not
    ``posts.canonical_key``, is the v1↔v2 bridge (the two key spaces never match:
    one is a slug, the other an ``imdb:`` id, and a join between them returns zero
    rows, which is exactly the silent wrong answer this module must not produce).

    Runtime and the work's own `languages` come from `cat_works`; the rung and the
    print's `audio_languages` come from `cat_releases`, which is the row that
    actually carries per-print facts.
    """
    if not post_ids:
        return {}
    marks = ",".join("?" * len(post_ids))
    out: dict = {}
    rows = conn.execute(
        f"""
        SELECT cs.post_id AS post_id,
               w.runtime_minutes AS runtime_minutes,
               w.languages AS languages
        FROM cat_work_sites cs
        JOIN cat_works w ON w.id = cs.work_id
        WHERE cs.post_id IN ({marks})
        """,
        post_ids,
    ).fetchall()
    for r in rows:
        entry = out.setdefault(int(r["post_id"]), _empty_evidence())
        if entry["runtime_minutes"] is None and r["runtime_minutes"]:
            try:
                entry["runtime_minutes"] = float(r["runtime_minutes"])
            except (TypeError, ValueError):
                pass
        for value in (r["languages"],):
            if value:
                entry["languages"].update(
                    part.strip().lower() for part in re.split(r"[,;/|\[\]\"]", str(value))
                    if part.strip())
    rung_rows = conn.execute(
        f"""
        SELECT cs.post_id AS post_id, r.resolution AS resolution,
               r.audio_languages AS audio_languages
        FROM cat_work_sites cs
        JOIN cat_releases r ON r.work_id = cs.work_id
        WHERE cs.post_id IN ({marks})
        """,
        post_ids,
    ).fetchall()
    for r in rung_rows:
        entry = out.setdefault(int(r["post_id"]), _empty_evidence())
        label = normalize_resolution(r["resolution"])
        if label:
            entry["resolutions"].add(label)
        if r["audio_languages"]:
            entry["languages"].update(
                part.strip().lower() for part in re.split(r"[,;/|\[\]\"]", str(r["audio_languages"]))
                if part.strip())
    return out


def _score(evidence: dict, hints: dict) -> tuple:
    """Split the hints the viewer gave into agreed, contradicted, and unanswerable."""
    matched, mismatched, unknown = [], [], []

    def judge(name, verdict):
        if verdict is True:
            matched.append(name)
        elif verdict is False:
            mismatched.append(name)
        else:
            unknown.append(name)

    if "duration_s" in hints:
        judge("duration_s",
              duration_matches(evidence.get("runtime_minutes"), hints["duration_s"]))
    if "resolution" in hints:
        held = evidence.get("resolutions") or set()
        if not held:
            unknown.append("resolution")
        elif hints["resolution"] in held:
            matched.append("resolution")
        else:
            mismatched.append("resolution")
    if "audio_language" in hints:
        held = evidence.get("languages") or set()
        wanted = hints["audio_language"]
        if not held:
            unknown.append("audio_language")
        elif any(wanted in lang or lang in wanted for lang in held):
            matched.append("audio_language")
        else:
            mismatched.append("audio_language")
    return matched, mismatched, unknown


def search_by_media(conn, title: str = "", duration_s=None, resolution=None,
                    audio_language: str = "", limit: int = 10, full: bool = False,
                    enrich=None) -> dict:
    """Read-only by-media lookup.

    ``enrich`` is the caller's chance to add the art handles and the work reference
    this module cannot mint (both are ``viewer`` concerns); it is called as
    ``enrich(item, row)`` with the already-projected item and its raw row.
    """
    clean = re.sub(r"\s+", " ", str(title or "")).strip()
    if not clean:
        return {
            "success": False,
            "error": ("A title is required: duration and resolution alone match "
                      "thousands of works in this catalog."),
            "results": [], "total": 0, "candidates": 0,
        }
    if len(clean) < MIN_QUERY_CHARS:
        # Deliberately no SQL at all. This is the request that used to cost the most:
        # measured at the live edge, `q=love` took 45 s and `q=a` never returned.
        return {
            "success": True,
            "query": {"title": clean, "duration_s": None, "resolution": None,
                      "audio_language": None},
            "duration_tolerance": DURATION_TOLERANCE,
            "candidates": 0,
            "total": 0,
            "results": [],
            "hint": (f"Type at least {MIN_QUERY_CHARS} characters of a title. A single "
                     f"character matches nearly the whole catalog, and ranking that "
                     f"many works is not a search."),
        }
    limit = min(50, max(1, int(limit or 10)))
    hints: dict = {}
    wanted_resolution = normalize_resolution(resolution)
    if wanted_resolution:
        hints["resolution"] = wanted_resolution
    if duration_s not in (None, "", 0):
        try:
            seconds = float(duration_s)
        except (TypeError, ValueError):
            seconds = 0.0
        if seconds > 0:
            hints["duration_s"] = seconds
    language = str(audio_language or "").strip().lower()
    if language:
        hints["audio_language"] = language

    window = min(CANDIDATE_WINDOW, max(limit * 4, limit))
    rows, tier = _candidates(conn, clean, window, full)
    ids = [int(r["id"]) for r in rows]
    counts = _counts_for(conn, ids)

    evidence = _work_evidence(conn, ids)
    scored = []
    for r in rows:
        pid = int(r["id"])
        ev = evidence.get(pid) or _empty_evidence()
        matched, mismatched, unknown = _score(ev, hints)
        scored.append((
            tier.get(pid, 0),
            len(matched) - len(mismatched),
            sum(counts.get(pid, [0, 0])),
            pid, r, ev, matched, mismatched, unknown,
        ))
    # The key is the old `ORDER BY (release_count + source_count) DESC, p.id DESC`
    # with the title's own strength in front of it, applied to the capped window
    # instead of to every group the catalog can produce. `pid` last is not
    # decoration: without a total order a tie repeats a row on the next page or drops
    # one, and the window is exactly where ties are most likely.
    scored.sort(key=lambda t: (-t[0], -t[1], -t[2], -t[3]))

    results = []
    for _, _, _, _, r, ev, matched, mismatched, unknown in scored[:limit]:
        pid = int(r["id"])
        releases, sources = counts.get(pid, [0, 0])
        item = redact.project(r, "post_brief")
        if full:
            item.update({"source_site": r["source_site"], "url": r["url"],
                         "slug": r["slug"]})
        # `release_count` and `source_count` were columns of the old statement's row,
        # so the public projection carried them. The by-media row must answer the same
        # keys as a `q=` row — `RouteShape` fails the build if it loses either.
        item.update({
            "release_count": releases,
            "source_count": sources,
            "runtime_minutes": ev.get("runtime_minutes"),
            "resolutions": sorted(ev.get("resolutions") or ()),
            "matched_on": matched,
            "mismatched_on": mismatched,
            "unknown_on": unknown,
        })
        if enrich is not None:
            enrich(item, r)
        results.append(item)
    return {
        "success": True,
        "query": {
            "title": clean,
            "duration_s": hints.get("duration_s"),
            "resolution": hints.get("resolution"),
            "audio_language": hints.get("audio_language"),
        },
        "duration_tolerance": DURATION_TOLERANCE,
        "candidates": len(rows),
        "total": len(results),
        "results": results,
    }
