#!/usr/bin/env python3
"""
Fast_Fetch/tiers.py — one best and fastest option per quality tier.
════════════════════════════════════════════════════════════════════
The ledger holds ~3.07M links for ~97k titles: a movie in one quality often has
six copies on six servers. A viewer does not want six links, and a list of them
is also the single thing that would make our catalog cloneable by someone else.
So every presentation surface collapses those copies to **one winner per quality
band** — the owner's "Auto default + visible quality switch": the player starts
at the best tier it can actually play, and the user may switch between 480p,
720p, 1080p and 4K, each showing exactly one link.

What "best" means here, in the order the owner set it:

1. **Can our one player play it** — a direct file outranks a link that needs a
   server-side resolve, which outranks a download-only file. An embed/iframe
   copy is never a play winner at all: the in-app answer for a tier whose only
   copy is an embed is "Download only", with no hidden failure behind it.
2. **Live, not dead** — a dead copy never wins over a live one.
3. **Speed we measured or the preference we earned** — ``SERVER_PREFERENCE`` is
   the ordering the healers already use between servers; it is applied here as a
   *sort key only* and never published, because it is a hoster name.
4. **Range support** (seek + resume), **freshness of the last check**, and
   **size sanity** for the band a 4K file that weighs 300 MB is a mislabel.

Only the winner's opaque handle, its behaviour and the print's own descriptor
leave the box — see ``redact.py`` for why nothing else can.
"""

from __future__ import annotations

import json

#: Canonical bands, best first. Anything a scraper wrote that does not resolve to
#: one of these is ``UNSPECIFIED`` and sorts last within its own tier.
BANDS = ("2160p", "1080p", "720p", "480p", "sd")
UNSPECIFIED = "unspecified"

#: How many same-band runner-ups travel with the winner. Two is enough to survive
#: one CDN refusing us, and it is still a silent list the user never sees.
BACKUP_LIMIT = 2

#: Weight of each playback kind. A direct file needs nothing from us; a page link
#: needs our resolver; a download is not playable here; an embed is not playable
#: at all and is therefore not a candidate for the play ladder. Both vocabularies
#: are accepted: the ledger's own words (`url`, `iframe`) and the public ones
#: `viewer.link_view` puts on a link (`resolve`, `external` — we never write the
#: word "embed" into a response, because a hoster in this catalog is named that).
KIND_WEIGHT = {
    "direct": 100,
    "url": 70,
    "resolve": 70,
    "download": 30,
    "iframe": 0,
    "embed": 0,
    "external": 0,
}

#: Measured verdicts that name a copy nothing can play. A dead link must never
#: win a quality band or be called playable, however good its other evidence is.
DEAD_STATES = ("dead", "broken", "gone")
#: Quarantine (serve_verify, Player Fix v2): a link whose journal earned the
#: strike rule is excluded from every serve path, not merely scored 0.
#: It is deliberately NOT in DEAD_STATES — the five-word unplayable
#: vocabulary is pinned elsewhere — but `score`/`playable` treat it as dead
#: and `for_release` drops it from the candidate pool entirely.
QUARANTINED_STATES = ("quarantined",)
#: A signed link whose window elapsed 403s exactly like a dead one, but its URL
#: can be re-resolved — so it loses any bonus and never plays, yet is not zeroed.
EXPIRED_STATES = ("expired", "unreachable")
#: Everything the play surfaces must refuse, whichever vocabulary wrote it.
UNPLAYABLE_STATES = DEAD_STATES + EXPIRED_STATES

#: Bytes a print of this band should plausibly weigh. Outside the window the copy
#: is either mislabelled or a truncated upload, so it loses the tie.
_SIZE_WINDOW = {
    "2160p": (2_500_000_000, 30_000_000_000),
    "1080p": (700_000_000, 9_000_000_000),
    "720p": (250_000_000, 4_000_000_000),
    "480p": (80_000_000, 1_500_000_000),
    "sd": (40_000_000, 1_200_000_000),
}

#: Order between servers, best first. This is a *sort key*: it is applied inside
#: the SQL that fetches candidates and no field carrying it is ever serialised.
#: The names come from the resolvers that earned them (the 10 Gbps bridge beats a
#: generic drive link beats an iframe), not from anything a client may see.
SERVER_PREFERENCE = (
    "hubcloud_10g", "fsl_r2", "google_cdn", "pixeldrain", "vegadrive",
    "fastdl", "gamerxyt", "direct-cloud", "greenmotors", "vidout", "vidbolt",
    "gdrive", "hubcloud", "mixdrop", "vidmoly", "streamtape", "doodstream",
)

#: Per-band service priority (Phase C item 4) — the §5 table from the
#: grand-scale synthesis (grand-scale-synthesis-20261113.md), measured
#: 2026-11-13 on 14,089 links (2,000 titles, 797 hosts) plus the unwrap
#: yield test. Each band maps to (serve order, silent backups). "[U]" in
#: the synthesis means the host is only playable through its unwrapper;
#: the order below is the order to TRY, and the dispatcher routes each
#: service to its unwrapper. Only hosts with a measured alive% > 0
#: (direct) or a verified unwrap yield appear — a band with no measured
#: host has an empty serve list, and nothing is invented. Keys are
#: priority_band_key() output; "sd" is the canonical-band fallback for
#: 360p/240p (band_of collapses both to "sd"). The sooplive backup is the
#: DB service name "vod-normal-global-cdn-z02.sooplive.com" (the
#: synthesis shorthand is "sooplive"); "sooplive" is kept as an alias.
BAND_SERVICE_PRIORITY = {
    "1080p": (("fsl_r2", "vidbolt"), ("hubcloud",)),
    "720p": (("5centscdn", "mp4moviez", "fsl_r2"), ("hubcloud", "vidbolt")),
    "480p": (("archive_org", "mp4moviez", "fsl_r2"), ("themoviebox", "hubcloud")),
    "360p": (("mp4moviez",), ("themoviebox",)),
    "240p": (("mp4moviez",), ()),
    "sd": (("mp4moviez",), ("themoviebox",)),
    "auto": (("aryzap-vod",), ()),
    "unspecified": (("dramadog", "cloudstorage.naver.com", "hlscdn.vip"),
                    ("megacartoons", "vod-normal-global-cdn-z02.sooplive.com",
                     "sooplive")),
    "hd": (("pkembed", "mxdrop"), ()),
    "hevc": (("hubcdn",), ("fsl_r2",)),
    "2160p": ((), ("hubcloud",)),
}

#: SQL fragment for the ORDER BY that fetches a release's candidate links. Kept
#: here so v1 and v2 rank identically and there is one list to review.
def candidate_order_sql(alias: str = "", band: str | None = None) -> str:
    """ORDER BY fragment for a release's candidate links, direct-first.

    ``alias`` qualifies every column (``"s"`` for a JOIN query, where
    ``id`` and ``created_at`` exist on both sides); empty for a
    single-table query. The resolver's failover reads the same ranking,
    so a dead bridge copy is never tried before a live direct copy in
    the same release. ``band`` is a §5 priority-band key (see
    priority_band_key): when given, that band's measured serve + backup
    order leads and the global SERVER_PREFERENCE orders everything
    else; without it the global preference is the whole order, exactly
    as before.
    """
    prefix = f"{alias}." if alias else ""
    if band is not None:
        serve, backups = BAND_SERVICE_PRIORITY.get(band, ((), ()))
        ordered = list(serve) + list(backups)
        ordered += [name for name in SERVER_PREFERENCE if name not in ordered]
    else:
        ordered = list(SERVER_PREFERENCE)
    return f"""
    CASE {prefix}playback_type
        WHEN 'direct' THEN 1 WHEN 'url' THEN 2
        WHEN 'download' THEN 3 WHEN 'iframe' THEN 4 ELSE 5 END ASC,
    CASE {prefix}status WHEN 'active' THEN 0 WHEN 'dead' THEN 9
    WHEN 'quarantined' THEN 9 ELSE 5 END ASC,
    CASE {prefix}service""" + "".join(
    f"\n        WHEN '{name}' THEN {index}"
    for index, name in enumerate(ordered)) + f"""
    ELSE {len(ordered)} END ASC,
    {prefix}is_temporary ASC,
    {prefix}is_resumable DESC,
    COALESCE({prefix}last_checked_at, {prefix}created_at) DESC,
    {prefix}id ASC
"""


CANDIDATE_ORDER_SQL = candidate_order_sql()

_BAND_RE_PATTERNS = (
    ("2160p", ("2160", "4k", "uhd", "hdr")),
    ("1080p", ("1080", "full hd", "fhd")),
    ("720p", ("720", "hd rip")),
    ("480p", ("480", "sdrip", "sd rip")),
    ("sd", ("360", "240", "400p", "cam", "hdts", "hd-ts")),
)


def band_of(*texts) -> str:
    """Which quality band a scraper's free-text describes, or ``unspecified``.

    Reads the release's own ``quality``/``codec``/``size`` columns — never a link
    field, because a link says who serves a file and a band says what the file
    is."""
    blob = " ".join(str(t).lower() for t in texts if t)
    for band, needles in _BAND_RE_PATTERNS:
        if any(needle in blob for needle in needles):
            return band
    # 388k of this catalog's releases say only "HD", which means 720p or better.
    # Promising 720p when the file is 1080p costs the user one notch on a switch
    # they can move; promising 1080p when it is 720p shows them a blurry picture
    # under a label they trusted. The conservative reading wins.
    if "hd" in blob or "hdtv" in blob:
        return "720p"
    return UNSPECIFIED


def priority_band_key(*texts) -> str:
    """Which §5 priority band a release's quality text maps to.

    Like band_of, but it keeps the distinctions the measured priority
    table needs: the "auto" HLS band, the bare-"HD" band, the hevc
    variants, and 360p vs 240p (both collapse to "sd" in band_of).
    Falls back to band_of for everything else.
    """
    blob = " ".join(str(t).lower() for t in texts if t).strip()
    if "hevc" in blob or "h265" in blob or "x265" in blob:
        return "hevc"
    if blob == "auto":
        return "auto"
    if blob in ("hd", "hdtv"):
        return "hd"
    if "360" in blob:
        return "360p"
    if "240" in blob:
        return "240p"
    return band_of(*texts)


def band_service_bonus(service: str, band: str) -> int:
    """The §5 priority bonus for a service in a band: serve order first.

    Serve position 0 earns +25, then +20, +15 (one notch per position);
    a silent backup earns +10, then +5, then 0. An unlisted service earns
    0 — it is still a candidate, just not a measured one. The bonus is
    sized so it orders copies of the SAME kind (direct 100 vs url 70 is
    a 30 gap, and +25 never closes it): the measured host order decides
    within a kind, never across one.
    """
    entry = BAND_SERVICE_PRIORITY.get(band)
    if not entry:
        return 0
    serve, backups = entry
    name = (service or "").strip().lower()
    if name in serve:
        return 25 - 5 * serve.index(name)
    if name in backups:
        return max(10 - 5 * backups.index(name), 0)
    return 0


def band_rank(band: str) -> int:
    """0 for the best band, ascending; ``unspecified`` last."""
    if band == UNSPECIFIED:
        return len(BANDS)
    return BANDS.index(band) if band in BANDS else len(BANDS)


def scope_sort_key(season, episode):
    """Order one title's prints the way a viewer expects: movie first, then
    season, then episode.

    Scrapers write these columns as text as often as as numbers ("1", "S02",
    "2: Season Two"), so a bare tuple sort raises the moment a string meets an
    int. The leading number is what a season really means here; text without one
    sorts last, and `None` (a movie, no season at all) sorts first."""
    import re as _re

    def number(value):
        if value is None:
            return (0, "")
        if isinstance(value, (int, float)):
            return (1, "%012.3f" % value)
        match = _re.search(r"\d+", str(value))
        return (2, "%012d" % int(match.group())) if match else (3, str(value))

    return (number(season), number(episode))


def _seconds_since(value) -> float | None:
    from datetime import datetime, timezone
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            stamp = datetime.strptime(text[:19], fmt)
        except ValueError:
            continue
        delta = datetime.now(timezone.utc) - stamp.replace(tzinfo=timezone.utc)
        return delta.total_seconds()
    return None


#: API_V2.md §7.1 / §6.3 — the two scales axis 2 can be on, as data. A projection
#: prior (0..900) and a measured score (0..1000) are *not* comparable, and a client
#: that re-ranks offline must know which one it is holding: a 750 prior means "this
#: looks like a live CDN direct", a 750 measured means "we knocked on it and it did".
PRIOR_SCALE = "projection_prior"
MEASURED_SCALE = "measured"
SCALE_RANGES = {PRIOR_SCALE: (0, 900), MEASURED_SCALE: (0, 1000)}
#: `cat_links.measured_ceiling` is not a column; the ceiling is a property of the
#: measured formula (`link_health.score_link` tops out at 930 for a describable
#: link), published so a client can clamp its own re-ranking without guessing.
MEASURED_CEILING = 930


def scale_of(link) -> str:
    """Which scale this link's `rank_score` is currently on (§7.1).

    The projector decides it and says so: `_blend_link()` returns the measured
    flag only when the evidence journal holds a *probe* that agrees with the
    newest verdict, and keeps the structural prior otherwise — a client report
    confirms a verdict but never measures a protocol, so it cannot move a link
    onto the measured scale. A link view with no flag at all (a raw ledger row,
    which v1 also ranks) is unmeasured by definition."""
    row = link if isinstance(link, dict) else dict(link)
    flag = row.get("measured")
    if flag is None:
        # A raw `cat_links`/ledger row: timings only exist once a probe wrote them.
        flag = row.get("latency_ms") is not None or row.get("speed_mbps") is not None
    return MEASURED_SCALE if bool(flag) else PRIOR_SCALE


def score_range(link) -> list:
    """The declared range for this link's score — [0, 900] or [0, 1000]."""
    return list(SCALE_RANGES[scale_of(link)])


def score(link, band: str = UNSPECIFIED, priority_key: str | None = None) -> int:
    """One integer per candidate: higher wins. Deterministic, no network.

    Accepts either a ledger row or an already-projected public link, because v1
    ranks raw rows and v2 ranks its own views; it reads only keys that are legal
    in a public body plus ``service``/``source_name`` when they are present,
    which are used as a sort key and never returned. ``priority_key`` is the §5
    band (priority_band_key); without it the canonical band is used, which is
    exact for 1080p/720p/480p/2160p/unspecified and falls back to the "sd"
    entry for 360p/240p."""
    row = link if isinstance(link, dict) else dict(link)
    kind = str(row.get("kind") or row.get("playback_type") or "").lower()
    value = KIND_WEIGHT.get(kind, 40)
    state = str(row.get("status") or row.get("state") or "").lower()
    if state in ("active", "live", "ok"):
        value += 40
    elif state in QUARANTINED_STATES:
        # Quarantine is exclusion, not a demotion: a quarantined copy is
        # not a candidate at all, whatever its other evidence says.
        return 0
    elif state in DEAD_STATES:
        # Audit critical 10: a dead copy is not a candidate. One −60 inside a
        # stack of bonuses (kind 100 + resumable + HTTP + speed) could still
        # leave it top of its band; link_health.score_link already says 0 for a
        # failed probe, so the ranking agrees with the measurement.
        return 0
    elif state in EXPIRED_STATES:
        # A lapsed signature voids every measurement made while it was valid:
        # speed and range support describe a fetch that now 403s. The kind's
        # own weight is all an expired copy may keep, so it always trails any
        # live or unchecked copy of the same kind — but it can be re-resolved,
        # which a dead one cannot, so it is not zeroed.
        return max(value - 60, 0)
    if row.get("http_status") and 200 <= int(row["http_status"]) < 400:
        value += 15
    if row.get("is_resumable") or row.get("resumable"):
        value += 15
    if row.get("rank_score"):
        # v2 already folded evidence into Layer-1's score; let it speak.
        value += min(int(row["rank_score"]), 200) // 4
    speed = row.get("speed_mbps")
    if speed:
        value += min(int(float(speed)), 100) // 5
    latency = row.get("latency_ms")
    if latency:
        value -= min(int(latency), 5000) // 100
    if row.get("is_temporary") or row.get("ephemeral"):
        value -= 10
    # §5 measured priority (Phase C item 4): a service with a measured
    # alive rate (or a verified unwrap) in this band earns a bonus that
    # orders copies of the same kind. The bonus never closes the kind
    # gap, so a measured host order decides within a kind, never across
    # one; an unlisted service earns 0 and is still a candidate.
    value += band_service_bonus(row.get("service"), priority_key or band)
    age = _seconds_since(row.get("last_checked_at") or row.get("last_evidence_at"))
    if age is not None:
        value += 10 if age < 14 * 86400 else (5 if age < 90 * 86400 else 0)
    size = row.get("file_size_bytes") or row.get("size_bytes")
    window = _SIZE_WINDOW.get(band)
    if size and window:
        value += 10 if window[0] <= int(size) <= window[1] else -10
    return max(value, 0)


def playable(link, band: str = UNSPECIFIED) -> bool:
    """Can our one player actually start this copy?

    An iframe is excluded even though it is a real link: it is only viewable by
    handing the user to another app's page, which is the surface the owner asked
    to remove. ``url`` counts because our resolver turns it into a stream.
    A state of dead/broken/gone/expired answers False whatever the kind or the
    projected ``playable`` boolean claims — a verdict measured against the
    endpoint outranks a label written at ingest (audit critical 10)."""
    row = link if isinstance(link, dict) else dict(link)
    state = str(row.get("status") or row.get("state") or "").lower()
    if state in UNPLAYABLE_STATES or state in QUARANTINED_STATES:
        return False
    kind = str(row.get("kind") or row.get("playback_type") or "").lower()
    if kind in ("iframe", "embed", "external"):
        return False
    if row.get("playable") is not None and isinstance(row.get("playable"), bool):
        return bool(row["playable"]) and kind != "download"
    return kind in ("direct", "url", "resolve") or bool(row.get("streamable"))


def for_release(release, links) -> dict:
    """Collapse one print's links into one winner per band.

    Returns ``{"tiers": [...], "auto": {...}}`` where each tier is exactly what a
    quality switch needs: the band, our own handle for the single best copy, how
    it behaves, whether it plays here or is download-only, and how many copies
    were folded into it. ``auto`` is the tier the player should start at."""
    row = release if isinstance(release, dict) else dict(release)
    # Only the structured columns decide a band. A release headline is a scraper's
    # sentence and can contain any word ("Camera", "Sand") that a band needle in
    # it would mis-read as a resolution.
    band = band_of(row.get("quality"), row.get("codec"), row.get("size"),
                   row.get("size_bytes"), row.get("resolution"),
                   row.get("quality_label"))
    # §5 priority key (Phase C item 4): the raw quality text keeps the
    # distinctions the measured table needs (auto, bare HD, hevc,
    # 360p vs 240p) that band_of collapses.
    pkey = priority_band_key(row.get("quality"), row.get("codec"),
                             row.get("size"), row.get("size_bytes"),
                             row.get("resolution"), row.get("quality_label"))
    # Quarantine is exclusion: a quarantined copy never reaches the
    # winner/backup pool at all — it is not merely outscored. A print
    # whose every copy is quarantined has no tiers, not a dead winner.
    def _state_of(item) -> str:
        item = item if isinstance(item, dict) else dict(item)
        return str(item.get("status") or item.get("state") or "").lower()

    candidates = [link for link in links
                  if _state_of(link) not in QUARANTINED_STATES]
    if not candidates:
        return {"tiers": [], "auto": None}
    scored = sorted(
        ((score(link, band, pkey), index, link) for index, link in enumerate(candidates)),
        key=lambda item: (-item[0], item[1]))
    winner = scored[0]
    play_winner = next((item for item in scored if playable(item[2], band)), None)
    # The print's stored audio languages — the rung's own words for what you
    # will hear, never a title-guessed language. Empty when the column is
    # empty: the row then shows no audio line rather than an invented one.
    # Audit #32: the column IS empty on most scraped rows (Rogmovies writes
    # the languages into the headline, not the column), so fall back to the
    # label parser — `describe()` reads the same headline the scraper
    # wrote ("Multi Audios [Tel + Tam + Mal + Kan]") and returns canonical
    # names. A print with neither still reports [], never a guess.
    audio = _split_languages(row.get("languages"))
    if not audio:
        try:
            import release_descriptor
            described = release_descriptor.describe(
                release_title=row.get("release_title") or "",
                quality=row.get("quality") or "",
                codec=row.get("codec") or "",
                languages=row.get("languages") or "")
            audio = list((described.get("audio") or {}).get("languages") or [])
        except Exception:      # noqa: BLE001 — a parser fault must not break the ladder
            audio = []
    tier = {
        "band": band,
        "quality": band if band != UNSPECIFIED else (row.get("quality") or "Available"),
        "label": _tier_label(row, band),
        "audio_languages": audio,
        "mode": "play" if play_winner else "download_only",
        "playable": bool(play_winner),
        "link": None,
        "copies": len(candidates),
        "backups": [],
    }
    chosen = play_winner or winner
    tier["link"] = chosen[2]
    # Silent failover needs a runner-up in the same band, not a different quality:
    # when the winner's CDN answers 403 mid-play, the player hops to the next copy
    # of the *same* rung at the exact position. Ranking is already done, so these
    # are free; they are the copies the collapse folded away, kept as candidates
    # rather than discarded (zero data loss). A play tier only fails over to
    # something that plays; a download-only tier fails over to other copies.
    pool = [item[2] for item in scored
            if item is not chosen and (playable(item[2], band) if play_winner else True)]
    tier["backups"] = pool[:BACKUP_LIMIT]
    auto = {"band": band, "playable": bool(play_winner)} if play_winner else None
    return {"tiers": [tier], "auto": auto}


def _split_languages(value) -> list:
    """The print's stored audio languages, as a list — never a guess.

    `releases.languages` is scraper-stored TEXT ("Hindi|Tamil", "English",
    or a JSON array like ``["Hindi", "Tamil"]`` — both shapes are in the
    ledger). Splitting it here keeps the wire honest: a rung shows only the
    languages its own print carries, and an empty column yields an empty
    list, so the row shows no audio line rather than a title-guessed
    language. (The label-parser fallback for an empty column lives in
    `for_release`, not here.)
    """
    if not value:
        return []
    text = str(value).strip()
    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            parsed = None
        if isinstance(parsed, list):
            seen = []
            for part in parsed:
                name = str(part).strip()
                if name and name not in seen:
                    seen.append(name)
            return seen
    seen = []
    for part in text.replace("|", ",").split(","):
        name = part.strip().strip("\"'[]")
        if name and name not in seen:
            seen.append(name)
    return seen


def _tier_label(release, band: str) -> str:
    """Netflix-style tier copy: what the picture is, never who serves it."""
    name = {"2160p": "4K Ultra HD", "1080p": "Full HD", "720p": "HD",
            "480p": "Good", "sd": "Standard"}.get(band) or "Available"
    parts = [name]
    codec = str((release if isinstance(release, dict) else dict(release))
                .get("codec") or "").strip()
    if codec and len(codec) <= 12 and not codec.lower().startswith(("x264 ", "h264 ")):
        parts.append(codec.upper())
    return " · ".join(parts)


def _same_link(left, right) -> bool:
    """Do these two views describe the same copy?

    Identity is the cheap case (the winner object itself). Otherwise the first
    key both sides carry decides it: ``stream_id`` is minted from the row id, so
    equal handles mean one copy seen twice, and different handles never do."""
    if left is right:
        return True
    for key in ("stream_id", "link_id", "id"):
        first = left.get(key) if hasattr(left, "get") else None
        second = right.get(key) if hasattr(right, "get") else None
        if first is not None and second is not None:
            return first == second
    return False


def merge(ladders) -> dict:
    """Merge per-print ladders into one quality switch for the whole title.

    Two prints in the same band (the usual case: the same movie scraped from two
    sites) are collapsed to their single best copy, so the user sees one row per
    quality. ``auto`` prefers the highest band that plays, then the best score.

    The collapse must not lose the failover pool: every copy each print offered
    (winner *and* runner-up) is kept, re-ranked across prints, and the best two
    that are not the winner travel with it as that band's backups. A user on
    1080p whose first CDN refuses mid-play still lands on 1080p."""
    by_band: dict[str, dict] = {}
    offered: dict[str, list] = {}
    for ladder in ladders:
        for tier in ladder.get("tiers", []):
            key = tier["band"]
            bucket = offered.setdefault(key, [])
            for item in [tier.get("link"), *(tier.get("backups") or [])]:
                if item is not None and not any(_same_link(item, held) for held in bucket):
                    bucket.append(item)
            current = by_band.get(key)
            # The fold counts every copy the band actually held, whoever won it: a
            # tie keeps the earlier print (stable) but still adds the newcomer, so
            # "6 copies collapsed into this row" stays the honest number.
            promoted = current if (current is not None
                                   and score(current["link"], key) >= score(tier["link"], key)) \
                else dict(tier)
            promoted["copies"] = (current["copies"] if current else 0) + tier["copies"]
            by_band[key] = promoted
    for key, tier in by_band.items():
        rest = [item for item in offered[key] if not _same_link(item, tier["link"])]
        if tier["playable"]:
            rest = [item for item in rest if playable(item, key)]
        rest.sort(key=lambda item: (-score(item, key), str(item.get("stream_id") or "")))
        tier["backups"] = rest[:BACKUP_LIMIT]
    tiers = sorted(by_band.values(), key=lambda tier: band_rank(tier["band"]))
    playable_tiers = [tier for tier in tiers if tier["playable"]]
    auto = None
    if playable_tiers:
        best = max(playable_tiers, key=lambda tier: (score(tier["link"], tier["band"]),
                                                     -band_rank(tier["band"])))
        auto = {"band": best["band"], "reason": "best", "stream_id":
                (best["link"] or {}).get("stream_id")}
    return {"tiers": tiers, "auto": auto,
            "download_only_bands": [tier["band"] for tier in tiers
                                    if not tier["playable"]]}
