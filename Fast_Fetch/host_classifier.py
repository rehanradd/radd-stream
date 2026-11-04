#!/usr/bin/env python3
"""
Fast_Fetch/host_classifier.py — Phase 1: classify a resolved link by host and
attach the request-header rules each host family actually requires.
════════════════════════════════════════════════════════════════════
Every link in the ledger belongs to one of three kinds, and the kinds need
different treatment downstream:

* **Category A — direct file.** The URL serves media bytes (MP4/MKV or a
  resumable stream endpoint): Cloudflare R2, FastDL (fastdl.beer), the Google
  Drive family, GoFile, PixelDrain. Playable and downloadable as-is, subject
  to each host's header rules.
* **Category B — HLS/embed player.** The URL is an embed page or a master
  playlist that needs (or already is) an HLS chain: Vidrift, StreamHG /
  hanerix (iqsmart's proven backend), Vidly (filmu), Modiplay / Cineverse,
  Vidbolt, and the classic embed families. Watch-only; segments are never a
  download candidate.
* **Category C — bridge.** The URL is an HTML landing / generation page that
  hides the real file (HubCloud, NexDrive, MobileJSR, Linkszilla, GreenMotors,
  GDFlix, FileBee/FilePress, VCloud...). Worthless without unwrapping.

Two rules from the host-knowledge docs drive the design:

1. **Classify by link host, never by service label.** The multimovies rows
   labelled ``gd-mirror`` / ``gdmirror`` / ``filesforever-mirror`` (~87,700
   rows) are all iqsmart watch pages. The label is a lie; the hostname is
   evidence. A URL is authoritative; a service label is only a fallback when
   no URL is available.
2. **Rank by backend, not front-end.** Modiplay's ``bingr`` server IS Vidrift
   and its ``streamhg`` server IS the same hanerix/StreamHG backend as
   iqsmart. ``classify(url=vidrift_link, service="cineverse")`` therefore
   returns backend ``vidrift``, so two copies of one file never count as two
   independent backups.

PixelDrain special case (measured failure, 2026-11-04): opening a saved
``/u/<id>`` link without the right headers answers ``hotlink_detected`` —
PixelDrain rejects a foreign ``Referer``/``Origin``. The fix implemented here
is two-part: rewrite ``/u/`` and ``/d/`` pages to the ``/api/file/<id>``
direct endpoint, and strip any non-pixeldrain ``Referer`` (plus ``Origin``)
from the request. Vidrift has the mirror-image rule: its master fetches
**require** ``Referer: https://embed.vidrift.net/`` (403 without it — proven
on the modiplay/bingr path).

⚠ TAXONOMY COLLISION (Phase-1 integration ruling, 2026-11-04): the letters
``A``/``B``/``C``/``?`` in :data:`CATEGORY_LABELS` name the **host kind**.
``resolved_cache.category`` reuses the same letters for a **different axis**
— the cache-horizon trust class its ``_derive_category`` derives from the
service label and URL markers (A = permanent-file trust, B = short-lived
packer trust). They are NOT interchangeable: ``gofile``/``1fichier``/
``megaup``/``hexload``/``desiupload`` and the raw Google-Drive host family
are kind-A here but horizon-B over there, while ``hubcloud`` is kind-C (a
bridge!) here yet horizon-A there. No caller may ever pass a
:data:`CATEGORY_LABELS` value into ``resolved_cache.category``; gating a
store happens through :func:`is_direct_file` / :func:`is_playable_category`
(bools), never through letters. See ``test_host_classifier.py``
``TestCategoryACrossCheckWithResolvedCache`` for the full measured
disagreement table.

And per Crown-Prince order qoder14 (Task A): this table is now the **single
authority for hoster classification** — ``site_scout.DEFAULT_HOSTER_KINDS``
is built from :func:`as_scout_hoster_kinds` with the legacy scout rows
appended as never-deleted fallback, not maintained beside it.

Python standard library only. No I/O in this module: it classifies and
prepares headers, it never fetches.
"""

from __future__ import annotations

import urllib.parse
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------

CATEGORY_DIRECT_FILE = "direct_file"      # Category A
CATEGORY_HLS_EMBED = "hls_embed"          # Category B
CATEGORY_BRIDGE = "bridge"                # Category C
CATEGORY_UNKNOWN = "unknown"

CATEGORY_LABELS = {
    CATEGORY_DIRECT_FILE: "A",
    CATEGORY_HLS_EMBED: "B",
    CATEGORY_BRIDGE: "C",
    CATEGORY_UNKNOWN: "?",
}

# ---------------------------------------------------------------------------
# Host table — (hostname marker, category, canonical backend)
#
# Matching is substring against the lower-cased hostname, first match wins,
# so more specific markers must come first. Families with "dozens of domains"
# (gdflix, hubcloud) match on the family substring, per host-power-weakness:
# one domain dying must not kill the family, but they share the pattern here;
# per-domain pass rates belong to the probe layer, not the classifier.
# ---------------------------------------------------------------------------

_HOST_TABLE: Tuple[Tuple[str, str, str], ...] = (
    # --- Category A: direct file hosts ---
    ("pixeldrain", CATEGORY_DIRECT_FILE, "pixeldrain"),
    ("drive.google", CATEGORY_DIRECT_FILE, "gdrive"),
    ("googleusercontent", CATEGORY_DIRECT_FILE, "gdrive"),
    ("drive.usercontent.google", CATEGORY_DIRECT_FILE, "gdrive"),
    ("firebasestorage.googleapis", CATEGORY_DIRECT_FILE, "gdrive"),
    ("r2.dev", CATEGORY_DIRECT_FILE, "r2"),
    ("r2.cloudflarestorage", CATEGORY_DIRECT_FILE, "r2"),
    ("cloudflarestorage", CATEGORY_DIRECT_FILE, "r2"),
    ("fastdl.beer", CATEGORY_DIRECT_FILE, "fastdl"),
    ("gofile", CATEGORY_DIRECT_FILE, "gofile"),
    ("1fichier", CATEGORY_DIRECT_FILE, "1fichier"),
    ("megaup", CATEGORY_DIRECT_FILE, "megaup"),
    ("vikingfile", CATEGORY_DIRECT_FILE, "vikingfile"),
    ("desiupload", CATEGORY_DIRECT_FILE, "desiupload"),
    ("hexload", CATEGORY_DIRECT_FILE, "hexload"),
    ("dailyuploads", CATEGORY_DIRECT_FILE, "dailyuploads"),
    ("frdl", CATEGORY_DIRECT_FILE, "frdl"),
    ("mega.nz", CATEGORY_DIRECT_FILE, "mega"),

    # --- Category B: HLS streams / embed players ---
    # vidrift before anything else so a modiplay-proxied master on
    # embed.vidrift.net is still backend "vidrift".
    ("vidrift", CATEGORY_HLS_EMBED, "vidrift"),
    ("bingr", CATEGORY_HLS_EMBED, "vidrift"),
    ("hanerix", CATEGORY_HLS_EMBED, "streamhg"),
    ("vibuxer", CATEGORY_HLS_EMBED, "streamhg"),
    ("streamhg", CATEGORY_HLS_EMBED, "streamhg"),
    ("iqsmartgames", CATEGORY_HLS_EMBED, "streamhg"),
    ("modiplay", CATEGORY_HLS_EMBED, "modiplay"),
    ("vidbolt", CATEGORY_HLS_EMBED, "vidbolt"),
    ("vidly", CATEGORY_HLS_EMBED, "vidly"),
    ("filmu", CATEGORY_HLS_EMBED, "vidly"),
    ("vidmoly", CATEGORY_HLS_EMBED, "vidmoly"),
    ("streamtape", CATEGORY_HLS_EMBED, "streamtape"),
    ("mixdrop", CATEGORY_HLS_EMBED, "mixdrop"),
    ("dood", CATEGORY_HLS_EMBED, "dood"),
    ("voe.sx", CATEGORY_HLS_EMBED, "voe"),
    ("vupload", CATEGORY_HLS_EMBED, "vupload"),
    ("vidoza", CATEGORY_HLS_EMBED, "vidoza"),
    ("filemoon", CATEGORY_HLS_EMBED, "filemoon"),
    ("vidsrc", CATEGORY_HLS_EMBED, "vidsrc"),
    ("vixsrc", CATEGORY_HLS_EMBED, "vixsrc"),
    ("vidhide", CATEGORY_HLS_EMBED, "vidhide"),
    ("autoembed", CATEGORY_HLS_EMBED, "autoembed"),

    # --- Category C: bridges (need unwrapping) ---
    # direct-cloud before generic "cloud" style markers on purpose.
    ("direct-cloud", CATEGORY_BRIDGE, "direct-cloud"),
    ("hubcloud", CATEGORY_BRIDGE, "hubcloud"),
    ("hubdrive", CATEGORY_BRIDGE, "hubcloud"),
    ("nexdrive", CATEGORY_BRIDGE, "nexdrive"),
    ("mobilejsr", CATEGORY_BRIDGE, "mobilejsr"),
    ("linkszilla", CATEGORY_BRIDGE, "linkszilla"),
    ("greenmotors", CATEGORY_BRIDGE, "greenmotors"),
    ("linkrit", CATEGORY_BRIDGE, "greenmotors"),
    ("gdflix", CATEGORY_BRIDGE, "gdflix"),
    ("gdtot", CATEGORY_BRIDGE, "gdflix"),
    ("filebee", CATEGORY_BRIDGE, "filebee"),
    ("filepress", CATEGORY_BRIDGE, "filebee"),
    ("vegadrive", CATEGORY_BRIDGE, "vegadrive"),
    ("gamerxyt", CATEGORY_BRIDGE, "gamerxyt"),
    ("hblinks", CATEGORY_BRIDGE, "hblinks"),
    ("fastilinks", CATEGORY_BRIDGE, "shortener"),
    ("wlinksi", CATEGORY_BRIDGE, "shortener"),
    ("mzgserver", CATEGORY_BRIDGE, "shortener"),
    ("10moviesz", CATEGORY_BRIDGE, "shortener"),
    ("vcloud", CATEGORY_BRIDGE, "vcloud"),
    ("mxdrop", CATEGORY_BRIDGE, "mxdrop"),
    ("pkembed", CATEGORY_BRIDGE, "pkembed"),
)

#: Service labels -> (category, backend). Only consulted when there is no URL,
#: and marked as label-derived — labels lie, hostnames don't.
_SERVICE_TABLE: Dict[str, Tuple[str, str]] = {
    "cineverse": (CATEGORY_HLS_EMBED, "modiplay"),
    "modiplay": (CATEGORY_HLS_EMBED, "modiplay"),
    "vidrift": (CATEGORY_HLS_EMBED, "vidrift"),
    "iqsmart": (CATEGORY_HLS_EMBED, "streamhg"),
    "streamhg": (CATEGORY_HLS_EMBED, "streamhg"),
    "vidbolt": (CATEGORY_HLS_EMBED, "vidbolt"),
    "vidout": (CATEGORY_HLS_EMBED, "vidout"),
    "filmu": (CATEGORY_HLS_EMBED, "vidly"),
    "pixeldrain": (CATEGORY_DIRECT_FILE, "pixeldrain"),
    "gdrive": (CATEGORY_DIRECT_FILE, "gdrive"),
    "gd-mirror": (CATEGORY_HLS_EMBED, "streamhg"),
    "gdmirror": (CATEGORY_HLS_EMBED, "streamhg"),
    "filesforever-mirror": (CATEGORY_HLS_EMBED, "streamhg"),
    "fsl_r2": (CATEGORY_DIRECT_FILE, "r2"),
    "google_cdn": (CATEGORY_DIRECT_FILE, "gdrive"),
    "vegadrive": (CATEGORY_BRIDGE, "vegadrive"),
    "hubcloud": (CATEGORY_BRIDGE, "hubcloud"),
    "hubcloud_10g": (CATEGORY_BRIDGE, "hubcloud"),
    "fastdl": (CATEGORY_DIRECT_FILE, "fastdl"),
    "direct-cloud": (CATEGORY_BRIDGE, "direct-cloud"),
    "greenmotors": (CATEGORY_BRIDGE, "greenmotors"),
    "gamerxyt": (CATEGORY_BRIDGE, "gamerxyt"),
    "streamtape": (CATEGORY_HLS_EMBED, "streamtape"),
    "mixdrop": (CATEGORY_HLS_EMBED, "mixdrop"),
    "doodstream": (CATEGORY_HLS_EMBED, "dood"),
    "vidmoly": (CATEGORY_HLS_EMBED, "vidmoly"),
}

# ---------------------------------------------------------------------------
# PixelDrain
# ---------------------------------------------------------------------------

PIXELDRAIN_FILE_ID_RE = r"/(?:u|d|api/file)/([A-Za-z0-9_-]+)"

# ---------------------------------------------------------------------------
# Result object
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Classification:
    """What a link is, where it lives, and which backend really serves it."""

    url: str
    host: str
    category: str
    backend: str
    source: str = "host"  # "host" (evidence) | "label" (fallback) | "none"
    details: Dict[str, str] = field(default_factory=dict)

    @property
    def letter(self) -> str:
        return CATEGORY_LABELS.get(self.category, "?")

    @property
    def is_direct(self) -> bool:
        return self.category == CATEGORY_DIRECT_FILE

    @property
    def is_hls_embed(self) -> bool:
        return self.category == CATEGORY_HLS_EMBED

    @property
    def is_bridge(self) -> bool:
        return self.category == CATEGORY_BRIDGE


def _hostname(url: str) -> str:
    try:
        return (urllib.parse.urlsplit(str(url or "")).hostname or "").lower()
    except ValueError:
        return ""


def pixeldrain_file_id(url: str) -> Optional[str]:
    """Return the PixelDrain file id in ``url`` (``/u/``, ``/d/`` or
    ``/api/file/`` shape), or None if it is not such a link."""
    import re

    m = re.search(PIXELDRAIN_FILE_ID_RE, str(url or ""))
    return m.group(1) if m else None


def is_pixeldrain(url: str) -> bool:
    return "pixeldrain" in _hostname(url)


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def classify(url: str = "", service: str = "") -> Classification:
    """Classify a link by its host, falling back to the service label only
    when the URL carries no recognised host.

    >>> classify("https://embed.vidrift.net/embed/movie/533444").letter
    'B'
    >>> classify("https://hubcloud.ist/drive/ABC123").letter
    'C'
    """
    host = _hostname(url)
    if host:
        for marker, category, backend in _HOST_TABLE:
            if marker in host:
                return Classification(
                    url=str(url or ""), host=host, category=category,
                    backend=backend, source="host",
                )
    label = str(service or "").strip().lower()
    if label and label in _SERVICE_TABLE:
        category, backend = _SERVICE_TABLE[label]
        return Classification(
            url=str(url or ""), host=host, category=category,
            backend=backend, source="label",
        )
    return Classification(
        url=str(url or ""), host=host, category=CATEGORY_UNKNOWN,
        backend="unknown", source="none" if not host else "host",
    )


def backend_of(url: str = "", service: str = "") -> str:
    """Canonical backend id — the dedup key for backup independence.

    Two copies of one title with the same backend are ONE backup, never two
    (modiplay/bingr == vidrift, modiplay/streamhg == iqsmart's StreamHG).
    """
    return classify(url, service).backend


# ---------------------------------------------------------------------------
# Header rules
# ---------------------------------------------------------------------------

_VIDRIFT_REFERER = "https://embed.vidrift.net/"


def _pop_case_insensitive(headers: Dict[str, str], name: str) -> Optional[str]:
    low = name.lower()
    for key in list(headers):
        if key.lower() == low:
            return headers.pop(key)
    return None


def prepare_request(url: str, headers: Optional[Dict[str, str]] = None,
                    service: str = "") -> Tuple[str, Dict[str, str]]:
    """Apply the per-host header/endpoint rules to a request.

    Returns ``(final_url, final_headers)``. The caller's dict is never
    mutated. Rules implemented (each traceable to a measured failure or a
    proven requirement in the host-knowledge docs):

    * **PixelDrain** — ``/u/<id>`` and ``/d/<id>`` page links are rewritten to
      the ``/api/file/<id>`` direct-stream endpoint (same unwrap as
      ``fast_fetch.unwrap_pixeldrain``), and a foreign ``Referer``/``Origin``
      is stripped: a non-pixeldrain Referer is exactly what triggers the
      ``hotlink_detected`` answer. A Referer already pointing at
      pixeldrain.com is kept, since PixelDrain serves its own pages.
    * **Vidrift (direct or modiplay-bingr)** — ``Referer`` is forced to
      ``https://embed.vidrift.net/``; every other value (including none)
      403s on the master/file fetch.
    """
    out = dict(headers or {})
    result = classify(url, service)

    if result.backend == "pixeldrain":
        file_id = pixeldrain_file_id(url)
        if file_id:
            url = f"https://pixeldrain.com/api/file/{file_id}"
        referer = _pop_case_insensitive(out, "Referer")
        _pop_case_insensitive(out, "Origin")
        if referer and "pixeldrain" in _hostname(referer):
            out["Referer"] = referer

    elif result.backend == "vidrift":
        _pop_case_insensitive(out, "Referer")
        _pop_case_insensitive(out, "Origin")
        out["Referer"] = _VIDRIFT_REFERER

    return url, out


def strip_hotlink_headers(headers: Dict[str, str]) -> Dict[str, str]:
    """Return ``headers`` without ``Referer``/``Origin`` — the PixelDrain
    hotlink fix on its own, for callers that already hold a direct
    ``/api/file/`` URL."""
    out = dict(headers)
    _pop_case_insensitive(out, "Referer")
    _pop_case_insensitive(out, "Origin")
    return out


# ---------------------------------------------------------------------------
# Storage predicates (Phase-1 integration ruling, item 2)
#
# These bools — never the CATEGORY_LABELS letters — are the gate that decides
# whether a URL may enter a playable cache row. Both return False for
# CATEGORY_BRIDGE and CATEGORY_UNKNOWN, so a bridge/HTML landing page or an
# unrecognised host can never be stored as a cached playable row.
# ---------------------------------------------------------------------------


def _to_classification(url_or_class, service: str = "") -> Classification:
    if isinstance(url_or_class, Classification):
        return url_or_class
    return classify(str(url_or_class or ""), service)


def is_direct_file(url_or_class, service: str = "") -> bool:
    """True only for Category A (the URL names a direct-file host)."""
    return _to_classification(url_or_class, service).category == CATEGORY_DIRECT_FILE


def is_playable_category(url_or_class, service: str = "") -> bool:
    """True for Category A and B (direct file or HLS/embed chain); False for
    Category C (bridge) and for unknown hosts.

    A False answer means: do NOT write this link into a playable cache row and
    do NOT 302 a player at it — unwrap (bridge) or refuse (unknown) first.
    """
    return _to_classification(url_or_class, service).category in (
        CATEGORY_DIRECT_FILE, CATEGORY_HLS_EMBED)


def is_bridge_category(url_or_class, service: str = "") -> bool:
    """True only for Category C — the URL is an HTML landing page that must
    be unwrapped before it means anything."""
    return _to_classification(url_or_class, service).category == CATEGORY_BRIDGE


# ---------------------------------------------------------------------------
# site_scout bridge — host_classifier is the SINGLE AUTHORITY for hoster
# classification (Crown-Prince order qoder14, Task A). site_scout keeps its
# own vocabulary ('direct'/'embed'/'bridge') and its legacy table for
# historical reasons; both are now derived from this table instead of
# drifting beside it. Legacy rows are never deleted (AGENTS.md rule 4) —
# site_scout appends them after these rows, and first-match-wins ordering
# makes the authority decisive.
# ---------------------------------------------------------------------------

#: This module's categories -> site_scout's kind words. ``unknown`` maps to
#: nothing: site_scout answers "unknown" only for hosts neither table knows.
SITE_SCOUT_KINDS = {
    CATEGORY_DIRECT_FILE: "direct",
    CATEGORY_HLS_EMBED: "embed",
    CATEGORY_BRIDGE: "bridge",
}

#: Resolved semantic disagreement (order qoder14): ``vcloud`` was
#: ``("vcloud", "embed")`` in site_scout's legacy table, but
#: host-power-weakness.md records VCloud as "Bridge -> Generate -> servers"
#: — a landing page whose server list is minted by a generate step, exactly
#: this table's Category C. The authority row (bridge) outranks the legacy
#: row; the legacy row stays in place, shadowed, un-deleted. The same logic
#: refined ``fastdl``: the family was SPLIT on evidence (fastdl.beer is a
#: direct file host; fastdlserver.site samples 404), so the authority names
#: only fastdl.beer direct and the legacy generic ``fastdl`` -> embed row
#: survives as fallback for the rest of the family.


def as_scout_hoster_kinds() -> Tuple[Tuple[str, str], ...]:
    """The authority table rendered in site_scout's ``(token, kind)``
    vocabulary, in decisive first-match order."""
    rows = []
    for marker, category, _backend in _HOST_TABLE:
        kind = SITE_SCOUT_KINDS.get(category)
        if kind is not None:
            rows.append((marker, kind))
    return tuple(rows)
