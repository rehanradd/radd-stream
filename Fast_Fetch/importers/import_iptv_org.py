#!/usr/bin/env python3
"""
import_iptv_org.py — Live TV channels from iptv-org (Pakistan + India).

iptv-org (https://github.com/iptv-org/iptv, Unlicense = public domain) is a
community collection of publicly available, legal live-TV streams as M3U
playlists, updated daily. This importer brings its Pakistan + India channels
into the Live TV registry (``Fast_Fetch/live_tv_registry.json``) — the same
registry the backend already serves at ``/api/v1/live-tv/channels`` — keeping
only streams verified alive by a real probe.

Sources (both are the same upstream data in different shapes):
  * API (preferred): https://iptv-org.github.io/api/streams.json plus
    channels.json (country, categories, is_nsfw), feeds.json (languages) and
    logos.json. Structured: url, referrer, user_agent, quality, labels
    (``Geo-blocked``, ``Not 24/7``). The country playlists are also fetched
    for enrichment only: a channel with no categories or no logo in the API
    data is rescued from its M3U entry (group-title / tvg-logo) instead of
    being dropped on a data gap.
  * M3U (fallback when any API file fails to fetch): the country playlists
    https://iptv-org.github.io/iptv/countries/pk.m3u and in.m3u, parsed
    directly (#EXTINF attrs, #EXTVLCOPT:http-referrer, ``(720p)`` quality
    suffix, feed language from the ``tvg-id`` ``@Feed`` suffix).

Probe discipline (repo standard, ``link_health.probe_many``): one capped
ranged GET per URL (<=32 KB, <=5 redirects, connect 5 s / total 10 s, max 10
parallel, max 2 per host enforced by the per-host gate, no retries).
Verdicts, from the probe result:
  * alive   — 200/206 AND the body is a real HLS playlist (``#EXTM3U``).
  * dead    — 404 / 410 / DNS failure only.
  * expired — 403 / 400 ONLY on a URL carrying real signature/expiry params
    (``ticket=``, ``signature=``, ``expires=`` …); a bare 403 is a bot-block.
  * unknown — everything else (timeout, 429, 5xx, bot-block 403, transport
    errors). Never marked dead on one probe, never stored, never deleted on.

Only verified-alive channels are stored. One stream per (channel, feed):
streams.json carries several mirrors per feed, so entries are grouped by
(display name, country) and the best URL goes first (no Referer required,
https, contains ``.m3u8``, highest quality); if the best URL is not alive the
next mirror is probed (each URL is probed at most once — that is not a retry).

Gotchas, handled explicitly:
  * Referer-gated channels (``referrer`` in the API, ``http-referrer`` in the
    M3U) are EXCLUDED from v1: the play path 302-redirects the client to the
    raw stream URL and the server never sends a Referer, so they cannot play
    yet. They are probed WITH their Referer so the report says whether they
    *would* play, and listed in the run summary as needing player support.
  * Ticketed URLs (``?profile=pass&ticket=…`` and friends) are NEVER stored
    and never probed — the ticket is a per-fetch session token. Listed in the
    run summary.
  * Geo-blocked / Not 24/7 channels ARE stored, with the label kept in the
    registry record (``labels``), never hidden silently.
  * The registry validator fails closed: a stored channel needs an https
    logo, an https stream URL containing ``.m3u8``, a known category and a
    language. http URLs are stored only when the probe lands on an https
    ``.m3u8`` URL (the landing URL is stored); bare-host URLs with no
    ``.m3u8`` anywhere are excluded. Categories outside the registry set are
    mapped (``general``/``business``/``culture``/``cooking``/``family``/
    ``documentary``/``series``/``comedy``/``lifestyle`` → the nearest allowed
    category; ``movies``/``education`` were added to the allowed set for
    this importer); unclassifiable groups (``undefined``, empty) are
    excluded, not guessed.
  * NSFW channels (``is_nsfw``) and closed channels are skipped.

Merge rules (idempotent — ``sync`` IS the daily refresh):
  * Existing channels are never removed. A candidate matching an existing
    channel (same name + country, or same stream URL) refreshes it: if its
    stored URL still probes alive, only ``verified_at`` is refreshed; if the
    stored URL is dead but the candidate URL is alive, the stream URL is
    repaired in place.
  * Every stored stream URL is re-probed on every run. An iptv-org row whose
    URL is not alive gains one strike (``consecutive_failures``); two
    consecutive strikes disable it (``enabled=false``, reason recorded) —
    never deleted, and a later alive probe (or a repaired URL) re-enables it
    only when it was strike-disabled, never when an operator disabled it.
  * Operator-curated rows (anything not ``source == "iptv-org"``) are only
    ever refreshed when alive; the importer never disables them.
  * New rows ship ``enabled=true`` with ``source="iptv-org"``. That is the
    operator's order for this import ("only working channels" — the channels
    are meant to be watched); the seed policy in ``live_tv.py`` about
    third-party restreams shipping disabled describes the original 23
    hand-picked rows, not this importer.

Daily refresh (no cron is wired by this module — the operator schedules it):
  ``0 4 * * * ubuntu python3 -S /opt/radd-stream/Fast_Fetch/importers/import_iptv_org.py sync --registry /opt/radd-stream/Fast_Fetch/live_tv_registry.json >> /home/ubuntu/iptv-org-sync.log 2>&1``
  (04:00 PKT, after the nightly prefetch sweep; the run re-probes every stored
  URL, adds newly-alive channels, strikes dead ones. A run takes a few
  minutes for ~1,000 probes.)

Usage:
  python3 -S Fast_Fetch/importers/import_iptv_org.py sync [--registry PATH]
      [--source auto|api|m3u] [--countries PK,IN] [--limit N] [--dry-run]
  python3 -S Fast_Fetch/importers/import_iptv_org.py verify [--registry PATH]
  python3 -S Fast_Fetch/importers/import_iptv_org.py stats [--registry PATH]

Stdlib only. No network in unit tests (probe + fetch are injectable).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import live_tv
from link_health import USER_AGENT, ProbeResult, probe_many

API_BASE = "https://iptv-org.github.io/api"
M3U_BASE = "https://iptv-org.github.io/iptv/countries"
COUNTRIES = ("PK", "IN")
SOURCE_TAG = "iptv-org"

FETCH_TIMEOUT_S = 20.0
PROBE_TIMEOUT_S = 10.0
PROBE_SAMPLE_BYTES = 32768
PROBE_WORKERS = 10
STRIKE_LIMIT = 2
MAX_URLS_PER_CHANNEL = 3

DEFAULT_REGISTRY = BASE_DIR / "live_tv_registry.json"

# iptv-org group -> registry category. Groups with no honest mapping
# ("undefined", "") are deliberately absent: those channels are excluded,
# not guessed into a category.
CATEGORY_MAP = {
    "news": "news",
    "sports": "sports",
    "entertainment": "entertainment",
    "music": "music",
    "kids": "kids",
    "religious": "religious",
    "travel": "travel",
    "movies": "movies",
    "general": "entertainment",
    "business": "news",
    "culture": "entertainment",
    "documentary": "entertainment",
    "animation": "kids",
    "series": "entertainment",
    "comedy": "entertainment",
    "family": "entertainment",
    "lifestyle": "entertainment",
    "cooking": "entertainment",
    "classic": "movies",
    "legislative": "news",
    "weather": "news",
    "education": "education",
    "science": "education",
    "shop": "entertainment",
    "auto": "entertainment",
    "outdoor": "entertainment",
}

# ISO 639-3 (feeds.json) -> ISO 639-1 (registry). Only the languages the
# PK/IN lists actually use, plus the usual majors.
LANG_639_3_TO_1 = {
    "urd": "ur", "hin": "hi", "pan": "pa", "ben": "bn", "tam": "ta",
    "tel": "te", "mal": "ml", "mar": "mr", "guj": "gu", "kan": "kn",
    "ori": "or", "asm": "as", "eng": "en", "ara": "ar", "fas": "fa",
    "pus": "ps", "san": "sa", "nep": "ne", "sin": "si", "snd": "sd",
    "tgl": "tl", "fil": "tl", "vie": "vi", "tha": "th", "zho": "zh",
    "jpn": "ja", "kor": "ko", "fra": "fr", "deu": "de", "spa": "es",
    "por": "pt", "rus": "ru", "tur": "tr", "ita": "it",
}

# Feed name (the @Feed suffix of a tvg-id, e.g. "GodStandsTV.pk@Urdu")
# -> ISO 639-1. "SD"/"HD"/"Main" carry no language and are absent.
FEED_LANGUAGE = {
    "urdu": "ur", "hindi": "hi", "punjabi": "pa", "bengali": "bn",
    "tamil": "ta", "telugu": "te", "malayalam": "ml", "marathi": "mr",
    "gujarati": "gu", "kannada": "kn", "odia": "or", "assamese": "as",
    "english": "en", "arabic": "ar", "pashto": "ps", "persian": "fa",
    "farsi": "fa", "nepali": "ne", "sindhi": "sd", "tagalog": "tl",
}

COUNTRY_LANGUAGE = {"PK": "ur", "IN": "hi"}

# Query params that mark a URL as session-bound (a per-fetch ticket or a
# signed, expiring link). Such URLs are never stored and never probed.
# "token" alone is not session-bound (some CDNs use stable tokens); it only
# counts when an expiry param rides with it.
SESSION_PARAMS = {
    "ticket", "signature", "sig", "sign", "expires", "exp",
    "authkey", "access_token",
}
SESSION_EXPIRY_PARAMS = {"expires", "exp", "timestamp"}

KNOWN_LABELS = ("Geo-blocked", "Not 24/7")

_MAINTENANCE_NOTE = (
    "Maintained by Fast_Fetch/importers/import_iptv_org.py "
    "(daily sync; see hidden_files/livetv-iptv-importer-20261113.md)."
)

_QUALITY_SUFFIX_RE = re.compile(r"\s*\((\d{3,4}p|4K|8K|HD|SD)\)\s*$", re.I)
_EXTINF_RE = re.compile(r"^#EXTINF:-?\d+\s*(.*?),(.*)$")
_ATTR_RE = re.compile(r'([\w-]+)="([^"]*)"')
_LABEL_RE = re.compile(r"\[([^\]]+)\]")
_DESCRIPTOR_FEEDS = {"SD", "HD", "4K", "UHD", "FHD", "Main", "MAIN"}


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z"


def _norm_name(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip().lower())


def _quality_rank(quality: str) -> int:
    """Higher = better, for picking the best mirror. Unknown = 0."""
    q = (quality or "").strip().lower()
    if q == "4k":
        return 2160
    if q == "8k":
        return 4320
    m = re.fullmatch(r"(\d{3,4})p", q)
    if m:
        return int(m.group(1))
    return 0


def _split_quality_suffix(name: str) -> tuple[str, str]:
    """'7 News (720p)' -> ('7 News', '720p'). 'Aaj Tak HD' is untouched."""
    m = _QUALITY_SUFFIX_RE.search(name or "")
    if not m:
        return (name or "").strip(), ""
    return name[: m.start()].strip(), m.group(1)


def has_session_params(url: str) -> bool:
    """True when the URL carries a per-fetch ticket or a signed expiry."""
    try:
        query = urllib.parse.parse_qsl(urllib.parse.urlparse(url or "").query)
    except ValueError:
        return False
    names = {k.lower() for k, _ in query}
    if names & SESSION_PARAMS:
        return True
    if "token" in names and names & SESSION_EXPIRY_PARAMS:
        return True
    return False


def map_category(groups) -> str:
    """First iptv-org group with an honest registry mapping, else ''."""
    for group in groups or []:
        for part in str(group or "").split(";"):
            mapped = CATEGORY_MAP.get(part.strip().lower())
            if mapped:
                return mapped
    return ""


@dataclass
class IptvEntry:
    """One candidate channel from iptv-org, before probing."""

    name: str
    country: str
    category: str
    language: str
    logo_url: str
    stream_url: str
    quality: str = ""
    referrer: str = ""
    labels: list = field(default_factory=list)
    tvg_id: str = ""
    feed: str = ""

    @property
    def key(self) -> tuple[str, str]:
        return (_norm_name(self.name), self.country)


# ── fetching ──────────────────────────────────────────────────────────────

def _fetch(url: str, opener=None, timeout: float = FETCH_TIMEOUT_S) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    open_fn = opener or urllib.request.urlopen
    with open_fn(req, timeout=timeout) as resp:
        return resp.read()


def _fetch_json(url: str, opener=None, timeout: float = FETCH_TIMEOUT_S):
    return json.loads(_fetch(url, opener, timeout).decode("utf-8"))


def fetch_api(opener=None):
    """The four API files. Raises on any fetch/parse failure (caller falls back)."""
    out = {}
    for name in ("streams", "channels", "feeds", "logos"):
        out[name] = _fetch_json("%s/%s.json" % (API_BASE, name), opener)
    return out


def fetch_m3u(countries, opener=None):
    """Country playlists as raw text, keyed by country code."""
    out = {}
    for country in countries:
        out[country] = _fetch(
            "%s/%s.m3u" % (M3U_BASE, country.lower()), opener
        ).decode("utf-8", errors="ignore")
    return out


# ── M3U parsing ───────────────────────────────────────────────────────────

def parse_m3u(text: str, country: str):
    """Parse one country playlist into entries + exclusion notes.

    Returns (entries, excluded) where excluded is a list of dicts
    {name, country, reason, url} for entries that could not be used.
    """
    entries: list[IptvEntry] = []
    excluded: list[dict] = []
    lines = (text or "").splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        i += 1
        if not line.startswith("#EXTINF:"):
            continue
        m = _EXTINF_RE.match(line)
        if not m:
            continue
        attrs = dict(_ATTR_RE.findall(m.group(1)))
        title = m.group(2).strip()
        referrer = attrs.get("http-referrer", "").strip()
        url = ""
        while i < len(lines):
            nxt = lines[i].strip()
            if nxt.startswith("#EXTINF:"):
                # Next entry already: this one has no URL. Do not swallow it.
                break
            i += 1
            if nxt.startswith("#EXTVLCOPT:"):
                opt = nxt[len("#EXTVLCOPT:"):]
                if opt.startswith("http-referrer="):
                    referrer = opt[len("http-referrer="):].strip()
                continue
            if nxt.startswith("#") or not nxt:
                continue
            url = nxt
            break
        if not url:
            continue
        tvg_id = attrs.get("tvg-id", "").strip()
        feed = ""
        if "@" in tvg_id:
            feed = tvg_id.rsplit("@", 1)[1].strip()
        name, quality = _split_quality_suffix(title)
        labels = [lab for lab in _LABEL_RE.findall(title) if lab in KNOWN_LABELS]
        name = _LABEL_RE.sub("", name).strip()
        group = attrs.get("group-title", "")
        category = map_category([group] if group else [])
        if not category:
            excluded.append({
                "name": name, "country": country,
                "reason": "no_category (group %r)" % (group or ""),
                "url": url,
            })
            continue
        if has_session_params(url):
            excluded.append({
                "name": name, "country": country,
                "reason": "ticketed (session params in URL)",
                "url": url,
            })
            continue
        logo = attrs.get("tvg-logo", "").strip()
        if not logo.startswith("https://"):
            excluded.append({
                "name": name, "country": country,
                "reason": "no_logo (no https tvg-logo)",
                "url": url,
            })
            continue
        language = FEED_LANGUAGE.get(feed.lower(), COUNTRY_LANGUAGE.get(country, ""))
        entries.append(IptvEntry(
            name=name, country=country, category=category, language=language,
            logo_url=logo, stream_url=url, quality=quality,
            referrer=referrer, labels=labels, tvg_id=tvg_id, feed=feed,
        ))
    return entries, excluded


def build_m3u_index(text: str):
    """tvg-id -> {group, logo_url}: enrichment index for the API path."""
    index = {}
    entries, _ = parse_m3u(text, "XX")
    for entry in entries:
        if entry.tvg_id and entry.tvg_id not in index:
            index[entry.tvg_id] = {
                "category": entry.category,
                "logo_url": entry.logo_url,
            }
    # Entries dropped by parse_m3u (no category / no logo) still carry a
    # group and a logo worth enriching with, so re-scan the raw lines.
    lines = (text or "").splitlines()
    for line in lines:
        if not line.startswith("#EXTINF:"):
            continue
        m = _EXTINF_RE.match(line.strip())
        if not m:
            continue
        attrs = dict(_ATTR_RE.findall(m.group(1)))
        tvg_id = attrs.get("tvg-id", "").strip()
        if tvg_id and tvg_id not in index:
            index[tvg_id] = {
                "category": map_category([attrs.get("group-title", "")]),
                "logo_url": attrs.get("tvg-logo", "").strip(),
            }
    return index


# ── API parsing ───────────────────────────────────────────────────────────

def _api_language(stream, feeds_by_key, country):
    rec = feeds_by_key.get((stream.get("channel"), stream.get("feed")))
    for code in (rec or {}).get("languages") or []:
        mapped = LANG_639_3_TO_1.get(str(code).lower())
        if mapped:
            return mapped
    return COUNTRY_LANGUAGE.get(country, "")


def _api_logo(stream, logos_by_key):
    for key in ((stream.get("channel"), stream.get("feed")),
                (stream.get("channel"), None)):
        rec = logos_by_key.get(key)
        if rec and (rec.get("url") or "").startswith("https://"):
            return rec["url"]
    return ""


def _api_display_name(stream):
    title = (stream.get("title") or "").strip()
    feed = (stream.get("feed") or "").strip()
    if (feed and feed not in _DESCRIPTOR_FEEDS
            and not re.fullmatch(r"\d{3,4}p", feed, re.I)
            and feed.lower() not in title.lower()):
        title = "%s (%s)" % (title, feed)
    name, suffix_quality = _split_quality_suffix(title)
    quality = (stream.get("quality") or "").strip() or suffix_quality
    return name, quality


def parse_api(data, countries=COUNTRIES, m3u_index=None):
    """Join the four API files into entries + exclusion notes.

    Returns (entries, excluded, counts) where counts tallies every stream
    seen, so the run summary can say what the API path dropped and why.
    """
    streams = data.get("streams") or []
    channels = {c.get("id"): c for c in (data.get("channels") or [])
                if isinstance(c, dict) and c.get("id")}
    feeds_by_key = {}
    for f in data.get("feeds") or []:
        if isinstance(f, dict):
            feeds_by_key.setdefault((f.get("channel"), f.get("id")), f)
    logos_by_key = {}
    for logo in data.get("logos") or []:
        if not isinstance(logo, dict) or not logo.get("in_use"):
            continue
        url = logo.get("url") or ""
        if not url.startswith("https://"):
            continue
        logos_by_key.setdefault((logo.get("channel"), logo.get("feed")), logo)
        logos_by_key.setdefault((logo.get("channel"), None), logo)

    entries: list[IptvEntry] = []
    excluded: list[dict] = []
    counts = Counter({"streams_seen": len(streams)})
    for stream in streams:
        if not isinstance(stream, dict):
            continue
        channel_id = stream.get("channel")
        if not channel_id:
            counts["no_channel"] += 1
            continue
        channel = channels.get(channel_id)
        if channel is None:
            counts["unknown_channel"] += 1
            continue
        country = channel.get("country")
        if country not in countries:
            counts["other_country"] += 1
            continue
        counts["in_scope"] += 1
        url = (stream.get("url") or "").strip()
        title = (stream.get("title") or channel.get("name") or channel_id).strip()
        if channel.get("is_nsfw"):
            counts["nsfw"] += 1
            excluded.append({"name": title, "country": country,
                             "reason": "nsfw", "url": url})
            continue
        if channel.get("closed"):
            counts["closed"] += 1
            excluded.append({"name": title, "country": country,
                             "reason": "closed channel", "url": url})
            continue
        if not url.startswith(("http://", "https://")):
            counts["bad_url"] += 1
            excluded.append({"name": title, "country": country,
                             "reason": "bad_url", "url": url})
            continue
        if has_session_params(url):
            counts["ticketed"] += 1
            excluded.append({"name": title, "country": country,
                             "reason": "ticketed (session params in URL)",
                             "url": url})
            continue
        category = map_category(channel.get("categories") or [])
        if not category and m3u_index:
            enriched = m3u_index.get(channel_id) or {}
            category = enriched.get("category") or ""
        if not category:
            counts["no_category"] += 1
            excluded.append({"name": title, "country": country,
                             "reason": "no_category (groups %r)"
                             % (channel.get("categories") or [],),
                             "url": url})
            continue
        logo = _api_logo(stream, logos_by_key)
        if not logo and m3u_index:
            enriched = m3u_index.get(channel_id) or {}
            logo = enriched.get("logo_url") or ""
        if not logo.startswith("https://"):
            counts["no_logo"] += 1
            excluded.append({"name": title, "country": country,
                             "reason": "no_logo (no https logo)",
                             "url": url})
            continue
        name, quality = _api_display_name(stream)
        labels = [lab for lab in (stream.get("labels") or [])
                  if lab in KNOWN_LABELS]
        entries.append(IptvEntry(
            name=name, country=country, category=category,
            language=_api_language(stream, feeds_by_key, country),
            logo_url=logo, stream_url=url, quality=quality,
            referrer=(stream.get("referrer") or "").strip(),
            labels=labels, tvg_id=channel_id,
            feed=(stream.get("feed") or "").strip(),
        ))
    return entries, excluded, counts


# ── dedupe (one stream per channel-feed, best URL first) ──────────────────

def _entry_sort_key(entry: IptvEntry):
    """Best mirror first: no Referer, https, .m3u8, highest quality."""
    return (
        1 if entry.referrer else 0,
        0 if entry.stream_url.startswith("https://") else 1,
        0 if ".m3u8" in entry.stream_url else 1,
        -_quality_rank(entry.quality),
    )


def group_candidates(entries):
    """{key: [entries best-first]} — at most MAX_URLS_PER_CHANNEL kept."""
    grouped: dict[tuple[str, str], list[IptvEntry]] = {}
    for entry in entries:
        grouped.setdefault(entry.key, []).append(entry)
    for key in grouped:
        grouped[key].sort(key=_entry_sort_key)
        grouped[key] = grouped[key][:MAX_URLS_PER_CHANNEL]
    return grouped


# ── verdicts ──────────────────────────────────────────────────────────────

def classify_verdict(result, url: str = "") -> str:
    """alive | dead | expired | unknown, from one probe result."""
    if result is None:
        return "unknown"
    if result.ok and result.protocol == "hls":
        return "alive"
    status = result.http_status or 0
    err = result.error or ""
    if status in (404, 410) or err in ("dns", "http_404", "http_410"):
        return "dead"
    if status in (400, 403) and (
            has_session_params(url or result.url)
            or has_session_params(result.redirects_to or "")):
        return "expired"
    return "unknown"


def storable_url(entry_url: str, result) -> str:
    """The URL to store for an alive probe, or '' when nothing is storable.

    Prefers the canonical entry URL (stable across days); takes the probe's
    landing URL only when the entry URL itself cannot be stored (plain http,
    or no ``.m3u8`` in it). A landing URL carrying session params is never
    stored.
    """
    candidates = [entry_url]
    if result is not None and result.redirects_to:
        candidates.append(result.redirects_to)
    for candidate in candidates:
        if not candidate:
            continue
        if has_session_params(candidate):
            continue
        if candidate.startswith("https://") and ".m3u8" in candidate:
            return candidate
    return ""


# ── probing ───────────────────────────────────────────────────────────────

def probe_candidates(grouped, probe_fn=probe_many, limit: int = 0):
    """Probe every candidate key until one mirror is alive-and-storable.

    Returns (resolved, report) where resolved is
    {key: (entry, store_url, result)} and report tallies verdicts and keeps
    the excluded keys (Referer-gated, dead, unknown, expired, no storable
    URL) with their names for the run summary.
    """
    keys = sorted(grouped)
    if limit and limit > 0:
        keys = keys[:limit]
    resolved: dict[tuple[str, str], tuple[IptvEntry, str, ProbeResult]] = {}
    report = {
        "verdicts": Counter(),
        "excluded": [],          # {name, country, reason, url}
        "probed_urls": 0,
        "referer_would_play": 0,
    }
    pending = {key: 0 for key in keys}  # key -> index into grouped[key]
    while pending:
        links = []
        batch: list[tuple[tuple[str, str], IptvEntry]] = []
        for key in sorted(pending):
            entry = grouped[key][pending[key]]
            link = {"url": entry.stream_url, "service": SOURCE_TAG}
            if entry.referrer:
                link["headers"] = {"Referer": entry.referrer}
            links.append(link)
            batch.append((key, entry))
        results = probe_fn(
            links, workers=PROBE_WORKERS, timeout=PROBE_TIMEOUT_S,
            sample_bytes=PROBE_SAMPLE_BYTES)
        report["probed_urls"] += len(results)
        for (key, entry), result in zip(batch, results):
            verdict = classify_verdict(result, entry.stream_url)
            report["verdicts"][verdict] += 1
            cur = pending[key]
            if entry.referrer:
                # Probed WITH its Referer so the report says whether it
                # would play — but it can never be stored in v1. If a clean
                # mirror is still untried, keep the key pending at it.
                if verdict == "alive":
                    report["referer_would_play"] += 1
                nxt = cur + 1
                if any(not e.referrer for e in grouped[key][nxt:]):
                    pending[key] = nxt
                    continue
                report["excluded"].append({
                    "name": entry.name, "country": entry.country,
                    "reason": "referrer required (%s) — would_play=%s"
                    % (entry.referrer, verdict == "alive"),
                    "url": entry.stream_url,
                })
                pending.pop(key, None)
                continue
            if verdict == "alive":
                store = storable_url(entry.stream_url, result)
                if store:
                    resolved[key] = (entry, store, result)
                    pending.pop(key, None)
                    continue
                report["verdicts"]["alive_no_store"] += 1
                # Alive but not storable: try the next mirror, if any.
            nxt = cur + 1
            if nxt < len(grouped[key]):
                pending[key] = nxt
                continue
            reason = verdict
            if verdict == "alive":
                reason = "alive_no_store (needs https + .m3u8)"
            report["excluded"].append({
                "name": entry.name, "country": entry.country,
                "reason": reason, "url": entry.stream_url,
            })
            pending.pop(key, None)
    return resolved, report


def probe_existing(channels, probe_fn=probe_many):
    """Probe every stream URL already in the registry. Returns {url: result}."""
    urls = []
    seen = set()
    for ch in channels:
        url = (ch or {}).get("stream_url") or ""
        if url and url not in seen:
            seen.add(url)
            urls.append(url)
    if not urls:
        return {}
    links = [{"url": url, "service": SOURCE_TAG} for url in urls]
    results = probe_fn(links, workers=PROBE_WORKERS, timeout=PROBE_TIMEOUT_S,
                       sample_bytes=PROBE_SAMPLE_BYTES)
    return {link["url"]: res for link, res in zip(links, results)}


# ── registry merge ────────────────────────────────────────────────────────

def merge_into_registry(data, resolved, existing_results, now):
    """Merge probe outcomes into the registry data (in place).

    Returns a Counter summary. Never removes a channel; never disables an
    operator-curated row; only strike-disables iptv-org rows (2 strikes).
    """
    channels = data.get("channels") or []
    summary = Counter()
    by_key = {}
    by_url = {}
    for ch in channels:
        if not isinstance(ch, dict):
            continue
        by_key[(_norm_name(ch.get("name") or ""), ch.get("country") or "")] = ch
        if ch.get("stream_url"):
            by_url[ch["stream_url"]] = ch
    next_id = 1
    for ch in channels:
        if isinstance(ch, dict) and isinstance(ch.get("id"), int):
            next_id = max(next_id, ch["id"] + 1)

    repaired_ids = set()
    # 1. Add new channels; repair matched rows whose stored URL is dead.
    for key, (entry, store_url, _result) in sorted(resolved.items()):
        existing = by_key.get(key) or by_url.get(store_url) \
            or by_url.get(entry.stream_url)
        if existing is None:
            record = {
                "id": next_id, "name": entry.name,
                "category": entry.category, "country": entry.country,
                "language": entry.language, "logo_url": entry.logo_url,
                "stream_url": store_url, "source": SOURCE_TAG,
                "verified_at": now, "enabled": True,
                "disabled_reason": "",
            }
            if entry.quality:
                record["quality"] = entry.quality
            if entry.labels:
                record["labels"] = list(entry.labels)
            channels.append(record)
            by_key[key] = record
            by_url[store_url] = record
            next_id += 1
            summary["added"] += 1
            continue
        stored = existing_results.get(existing.get("stream_url") or "")
        stored_alive = stored is not None and classify_verdict(stored) == "alive"
        if stored_alive:
            summary["existing_kept"] += 1
            continue
        existing["stream_url"] = store_url
        existing["verified_at"] = now
        existing.pop("consecutive_failures", None)
        if not existing.get("enabled") and str(
                existing.get("disabled_reason") or ""
        ).startswith("unreachable:"):
            existing["enabled"] = True
            existing["disabled_reason"] = ""
        repaired_ids.add(existing.get("id"))
        summary["existing_repaired"] += 1

    # 2. Refresh / strike every stored URL from its own probe.
    not_refreshed = []
    for ch in channels:
        if not isinstance(ch, dict):
            continue
        result = existing_results.get(ch.get("stream_url") or "")
        if result is None:
            continue
        if ch.get("id") in repaired_ids:
            continue
        verdict = classify_verdict(result)
        if verdict == "alive":
            ch["verified_at"] = now
            ch.pop("consecutive_failures", None)
            summary["existing_refreshed"] += 1
        else:
            not_refreshed.append({
                "name": ch.get("name") or "", "country": ch.get("country") or "",
                "verdict": verdict, "url": ch.get("stream_url") or "",
            })
        if verdict != "alive" and ch.get("source") == SOURCE_TAG:
            fails = int(ch.get("consecutive_failures") or 0) + 1
            ch["consecutive_failures"] = fails
            if fails >= STRIKE_LIMIT:
                ch["enabled"] = False
                ch["disabled_reason"] = (
                    "unreachable: %s (%d consecutive failed probes)"
                    % (verdict, fails))
                summary["existing_disabled"] += 1
            else:
                summary["existing_struck"] += 1
        # else: operator-curated row, not alive — leave it alone.
    summary["existing_not_refreshed"] = not_refreshed

    data["channels"] = channels
    data["updated_at"] = now
    note = data.get("note") or ""
    if _MAINTENANCE_NOTE not in note:
        data["note"] = (note + " | " + _MAINTENANCE_NOTE).strip(" |")
    return summary


def load_registry(path):
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    # validate_registry raises ValueError on a bad registry, returns the
    # data unchanged when it is good.
    live_tv.validate_registry(data)
    return data


def write_registry(path, data):
    live_tv.validate_registry(data)
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


# ── commands ──────────────────────────────────────────────────────────────

def run_sync(registry_path, source="auto", countries=COUNTRIES, limit=0,
             dry_run=False, opener=None, probe_fn=probe_many):
    """Fetch, probe, merge. Returns the run summary (dict)."""
    now = _now_iso()
    summary: dict = {
        "source_requested": source, "countries": list(countries),
        "limit": limit, "dry_run": dry_run, "now": now,
    }
    entries: list[IptvEntry] = []
    parse_excluded: list[dict] = []
    api_counts: Counter = Counter()
    used_source = source
    if source in ("auto", "api"):
        try:
            data = fetch_api(opener)
            m3u_index: dict = {}
            try:
                for country in countries:
                    text = fetch_m3u([country], opener)[country]
                    m3u_index.update(build_m3u_index(text))
            except Exception as exc:  # enrichment is best-effort only
                summary["m3u_enrichment_error"] = str(exc)[:200]
            entries, parse_excluded, api_counts = parse_api(
                data, countries, m3u_index or None)
            used_source = "api"
        except Exception as exc:
            if source == "api":
                raise
            summary["api_error"] = str(exc)[:200]
            used_source = "m3u"
    if used_source == "m3u":
        m3u_texts = fetch_m3u(countries, opener)
        for country in countries:
            country_entries, country_excluded = parse_m3u(
                m3u_texts[country], country)
            entries.extend(country_entries)
            parse_excluded.extend(country_excluded)
    summary["used_source"] = used_source
    summary["api_counts"] = dict(api_counts)
    summary["parse_excluded"] = parse_excluded

    grouped = group_candidates(entries)
    summary["candidate_keys"] = len(grouped)
    summary["candidate_urls"] = sum(len(v) for v in grouped.values())

    resolved, probe_report = probe_candidates(grouped, probe_fn, limit)
    summary["resolved"] = len(resolved)
    summary["probed_urls"] = probe_report["probed_urls"]
    summary["probe_verdicts"] = dict(probe_report["verdicts"])
    summary["referer_would_play"] = probe_report["referer_would_play"]
    summary["probe_excluded"] = probe_report["excluded"]

    registry = load_registry(registry_path)
    before = len(registry.get("channels") or [])
    existing_results = probe_existing(registry.get("channels") or [], probe_fn)
    summary["existing_probed"] = len(existing_results)
    merge_summary = merge_into_registry(
        registry, resolved, existing_results, now)
    summary["merge"] = dict(merge_summary)
    summary["channels_before"] = before
    summary["channels_after"] = len(registry.get("channels") or [])

    if dry_run:
        summary["written"] = False
        return summary
    write_registry(registry_path, registry)
    summary["written"] = True
    return summary


def run_verify(registry_path):
    data = load_registry(registry_path)
    channels = data.get("channels") or []
    by_country: Counter = Counter()
    by_category: Counter = Counter()
    by_source: Counter = Counter()
    for ch in channels:
        by_country[ch.get("country") or ""] += 1
        by_category[ch.get("category") or ""] += 1
        by_source[ch.get("source") or ""] += 1
    return {
        "channels": len(channels),
        "enabled": sum(1 for ch in channels if ch.get("enabled")),
        "by_country": dict(by_country),
        "by_category": dict(by_category),
        "by_source": dict(by_source),
    }


def _print_summary(summary):
    out = []
    out.append("iptv-org sync %s (source=%s, countries=%s, dry_run=%s)"
               % (summary["now"], summary["used_source"],
                  ",".join(summary["countries"]), summary["dry_run"]))
    if summary.get("api_error"):
        out.append("  API failed, fell back to M3U: %s" % summary["api_error"])
    if summary.get("m3u_enrichment_error"):
        out.append("  M3U enrichment skipped: %s"
                   % summary["m3u_enrichment_error"])
    if summary.get("api_counts"):
        counts = summary["api_counts"]
        out.append("  api streams: seen=%d in_scope=%d other_country=%d" % (
            counts.get("streams_seen", 0), counts.get("in_scope", 0),
            counts.get("other_country", 0)))
    out.append("  candidates: %d channel-feeds (%d urls)"
               % (summary["candidate_keys"], summary["candidate_urls"]))
    out.append("  probed: %d urls, verdicts: %s"
               % (summary["probed_urls"], summary["probe_verdicts"]))
    out.append("  resolved alive: %d (referer-gated that would play: %d)"
               % (summary["resolved"], summary["referer_would_play"]))
    merge_display = {k: v for k, v in summary["merge"].items()
                     if k != "existing_not_refreshed"}
    out.append("  registry: %d -> %d channels, merge: %s"
               % (summary["channels_before"], summary["channels_after"],
                  merge_display))
    not_refreshed = summary["merge"].get("existing_not_refreshed") or []
    if not_refreshed:
        out.append("  existing not refreshed (%d): %s"
                   % (len(not_refreshed),
                      ", ".join("%s [%s] (%s)"
                                % (r["name"], r["country"], r["verdict"])
                                for r in not_refreshed)))
    out.append("  written: %s" % summary["written"])
    for title, items in (
            ("parse exclusions", summary["parse_excluded"]),
            ("probe exclusions", summary["probe_excluded"])):
        by_reason: dict[str, list[dict]] = {}
        for item in items:
            by_reason.setdefault(item["reason"], []).append(item)
        out.append("  %s (%d):" % (title, len(items)))
        for reason in sorted(by_reason):
            names = ", ".join(
                "%s [%s]" % (it["name"], it["country"])
                for it in by_reason[reason])
            out.append("    %s: %d — %s" % (reason, len(by_reason[reason]), names))
    return "\n".join(out)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Live TV importer from iptv-org (Pakistan + India).")
    sub = parser.add_subparsers(dest="command", required=True)
    sync = sub.add_parser(
        "sync", help="fetch lists, probe, merge into the registry (idempotent)")
    sync.add_argument("--registry", default=str(DEFAULT_REGISTRY))
    sync.add_argument("--source", choices=["auto", "api", "m3u"],
                      default="auto")
    sync.add_argument("--countries", default=",".join(COUNTRIES),
                      help="comma-separated ISO codes, default PK,IN")
    sync.add_argument("--limit", type=int, default=0,
                      help="cap candidate channels probed (0 = no limit)")
    sync.add_argument("--dry-run", action="store_true",
                      help="probe and plan, do not write the registry")
    verify = sub.add_parser("verify", help="load + validate the registry")
    verify.add_argument("--registry", default=str(DEFAULT_REGISTRY))
    stats = sub.add_parser("stats", help="registry counts by country/category/source")
    stats.add_argument("--registry", default=str(DEFAULT_REGISTRY))
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.command == "sync":
        countries = tuple(c.strip().upper() for c in args.countries.split(",")
                          if c.strip())
        summary = run_sync(args.registry, args.source, countries,
                           args.limit, args.dry_run)
        print(_print_summary(summary))
        return 0
    if args.command == "verify":
        print(json.dumps(run_verify(args.registry), indent=2, sort_keys=True))
        return 0
    if args.command == "stats":
        print(json.dumps(run_verify(args.registry), indent=2, sort_keys=True))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
