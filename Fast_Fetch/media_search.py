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
            "results": [], "total": 0,
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

    where = [redact.adult_clause("p"), "(p.clean_title LIKE ? OR p.title LIKE ?)"]
    like = f"%{clean}%"
    params: list = [like, like]
    provenance_cols = ", p.source_site, p.url, p.slug" if full else ""
    rows = conn.execute(
        f"""
        SELECT p.id, p.clean_title, p.title, p.year, p.content_type, p.seasons,
               p.imdb_rating, p.imdb_id, p.tmdb_id, p.genres, p.is_animated,
               p.industry, p.country, p.language, p.poster_url, p.backdrop_urls
               {provenance_cols},
               COUNT(DISTINCT r.id) AS release_count,
               COUNT(DISTINCT s.id) AS source_count
        FROM posts p
        LEFT JOIN releases r ON r.post_id = p.id
        LEFT JOIN download_sources s ON s.release_id = r.id
        WHERE {" AND ".join(where)}
        GROUP BY p.id
        ORDER BY (release_count + source_count) DESC, p.id DESC
        LIMIT ?
        """,
        params + [min(CANDIDATE_WINDOW, max(limit * 4, limit))],
    ).fetchall()

    evidence = _work_evidence(conn, [int(r["id"]) for r in rows])
    scored = []
    for r in rows:
        ev = evidence.get(int(r["id"])) or _empty_evidence()
        matched, mismatched, unknown = _score(ev, hints)
        scored.append((
            len(matched) - len(mismatched),
            int(r["release_count"] or 0) + int(r["source_count"] or 0),
            int(r["id"]), r, ev, matched, mismatched, unknown,
        ))
    scored.sort(key=lambda t: (-t[0], -t[1], -t[2]))

    results = []
    for _, _, _, r, ev, matched, mismatched, unknown in scored[:limit]:
        item = redact.project(r, "post_brief")
        if full:
            item.update({"source_site": r["source_site"], "url": r["url"],
                         "slug": r["slug"]})
        item.update({
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
