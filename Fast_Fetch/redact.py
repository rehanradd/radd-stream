#!/usr/bin/env python3
"""
Fast_Fetch/redact.py — the public edge's deny-by-default projection layer.
═══════════════════════════════════════════════════════════════════════════
Everything the outside world may see is assembled here, in one place, so that
"what leaves the server" is a single list a reviewer can read — not a grep.

Three mechanisms, deliberately:

1. ``project(row, view)``  — allowlist by OUTPUT key. A row straight from
   ``SELECT *`` contributes nothing until a key is named in ``VIEWS[view]``, so
   adding a column to the ledger cannot publish itself. This is the only
   guarantee that survives a schema change nobody reviewed.
2. ``scrub(obj)``          — recursive deny-list, for the nested responses
   (work detail, play bundle) that are assembled by hand. Structural defence in
   depth; ``test_redact`` asserts scrub is already a no-op on those payloads.
3. ``assert_clean(text, needles)`` — sentinel scan. A value can escape under a
   renamed key; only a text search for the known site slugs and hoster names
   catches that.

Provenance itself is never lost: the ledger (``posts.source_site``,
``download_sources.service|source_name|source_url|final_url``, ``post_sources``,
``sitemap_cache.loc``) keeps recording it, unchanged, for healing and audit.
What changes is that it stops leaving the server as readable meaning.

Honest limits — this is metadata suppression, not access control:
  * ``/api/v1/stream`` and ``/api/v1/art`` are 302 redirectors, so a network
    trace shows the upstream host. The user's own eyes, the UI text, the API
    payloads and the shared catalog do not. Streaming bytes through this VM was
    rejected on load grounds; the redirect keeps upstream hosts out of the
    interface for zero per-byte cost.
  * Someone who decompiles the APK or replays a capture can reconstruct
    upstreams. Deciding that is the owner's, and it is accepted: the goal is the
    ordinary-user experience plus closing the real business hole — a third party
    rebuilding our catalog into their own app or website from our API.
  * Server logs and the database keep provenance by design. Operator-only
    provenance is served on a separate localhost port (see viewer.py).

Stdlib only, like the rest of the backend.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import os
import re
import sqlite3
import struct
import time
from pathlib import Path

# ── the vocabulary that must never be public ─────────────────────────────────

#: Key names that carry provenance wherever they appear. ``project`` never
#: emits them (they are absent from every allowlist by construction); ``scrub``
#: removes them from hand-built trees; the tests forbid them outright.
PROVENANCE = frozenset({
    # which site
    "source_site", "site", "sites", "site_name", "site_slug",
    # which upstream page
    "url", "loc", "slug", "page_url", "page_title", "origin_url",
    "intermediate_url", "source_url", "final_url", "source_slug", "source_title",
    # which hoster
    "service", "source_name", "resource_id", "hoster", "mirror",
    # our own identity keys: ours to keep, nobody else's primary key to mirror
    "canonical_key", "work_key",
})

#: Free-text keys a user reads. These need value-level cleaning, not only
#: key-level denial: a scraped headline is
#: ``"Title (2001) 480p BluRay x264 [470MB] – Nexdrive.fit"``, so the site or
#: hoster name lives *inside* the label we want to show. Hiding the column while
#: printing its title would hide nothing.
TEXT_KEYS = frozenset({
    "title", "clean_title", "release_title", "synopsis", "label", "print_label",
    "quality_label", "season_title", "episode_title", "name", "display_title",
    "original_title", "work_title", "alias", "chapter_title", "detail",
    "page_title", "source_title",
    # A scene-group token is scraped text, not a controlled vocabulary: an
    # all-caps site brand inside a release label would otherwise leave here
    # verbatim and name the site a title came from.
    "release_group",
})

#: Words that legitimately appear in our own labels and must never be treated
#: as a provenance needle. The state-machine vocabulary belongs to the last
#: group: a scraper that stored `service = "resumable"` describes how the link
#: behaves, not who runs it, and naming it a brand would make every honest label
#: look like a leak.
GENERIC_TOKENS = frozenset({
    "direct", "cdn", "cloud", "drive", "downloads", "download", "stream",
    "streaming", "instant", "fast", "free", "server", "servers", "online",
    "player", "mirror", "mirrors", "file", "files", "video", "videos", "movie",
    "movies", "series", "season", "seasons", "episode", "episodes", "dual",
    "audio", "hindi", "tamil", "telugu", "english", "dubbed", "unofficial",
    "update", "updated", "added", "watch", "hq", "hd", "sd", "full", "high",
    "premium", "quality", "pack", "batch", "multi", "subs", "subtitle",
    "subtitles", "web", "series", "point", "break", "x264", "x265", "hevc",
    "avc", "dvdscr", "bluray", "webrip", "cam", "ts", "print", "first",
    "unknown", "resumable", "temporary", "expired", "active", "dead",
    "status", "state", "link", "links", "new", "none", "null",
    "drop", "schema", "version", "speed",
    "http", "https", "click", "page", "pages", "upstream", "upload", "share",
    "send", "support", "fonts", "gateway", "google", "github", "imdb", "api",
    "embed", "american",
})

#: Image hosts we are willing to name in public. Art that is not already on one
#: of these is served through ``/api/v1/art`` so the upstream host stays ours to
#: see. Deliberately only third-party art CDNs, never a scraper's own domain.
PUBLIC_IMAGE_HOSTS = frozenset({
    "image.tmdb.org",
    "image.themoviedb.org",
    "www.themoviedb.org",
    "m.media-amazon.com",
    "assets-in.bmscdn.com",
    "i.ytimg.com",
    "encrypted-tbn0.gstatic.com",
    "occ-0-5264-3647.1.nflxso.net",
    "resizing.flixster.com",
})

#: Hoster/site tokens a public body must never contain, whatever key hides them.
#: ``site_needles()`` extends this with whatever the live data actually holds, so
#: the list cannot rot when a scraper is added.
BASE_NEEDLES = frozenset({
    "vegamovies", "rogmovies", "ssrmovies", "katmoviehd", "7starhd", "hdhub4u",
    "multimovies", "moviezguru", "rareanimes", "desicinemas", "9xmovies",
    "bolly4u", "filmyzilla", "10xflix", "hdtvb", "toonworld4all", "hindilinks4u",
    "pixeldrain", "vegadrive", "gamerxyt", "direct-cloud", "greenmotors",
    "hubcloud", "dropgalaxy", "clicknupload", "gdtot", "filepress", "fsl_r2",
    "megaup", "1fichier", "gofile", "vidout", "vidbolt", "vidrift", "vidbolt",
    "cineverse", "fastdl", "google_cdn", "movieshub", "short.ink", "vcloud",
    "mixdrop", "vidmoly", "bestx.stream", "dhtpre", "ryderjet", "morencius",
    "peytonepre", "movearnpre", "smoothpre", "nexdrive",
    # Added from the 109k-catalog sweep, where each of these was seen naming a
    # server inside a release label ("Make Me Tingle S01E01 Filmu", "… Vidzee
    # Mirror", "… Peachify Mirror", "The Judge Returns S01E01 IQSmart",
    # "… Stream Server GDMIRROR"). None of them occurs inside any real title in
    # the catalog (checked: 0 rows in `posts.clean_title`), which is the test a
    # plain English-shaped word has to pass before it may be deleted from copy.
    "filmu", "vidzee", "peachify", "iqsmart", "gdmirror", "filesforever",
    # The katmoviehd mirror family and the Google-Drive bridges, all seen naming
    # a server inside a label or a synopsis. The only two catalog titles that
    # contain "katmovie"/"gdrive" are themselves polluted headlines
    # ("Absolutely Anything 2015 BRRIP KATMOVIEHD Watch ONLINE", "Se7en 1995
    # Brrip x264 Gdrive"), so deleting them improves the text rather than
    # eating honest copy. "google drive" is a two-word hoster name: the phrase
    # never ends a real title, and `public_label` cannot emit it at all.
    "katmovie", "katmovie18", "katdrama", "katworld", "movieheist",
    "moviesbaba", "filmyflare", "gdirect", "gdrive", "g-drive", "google drive",
})

# ── views: the only thing that may be serialised ─────────────────────────────
#
# Output keys are ours. `id`/`stream_id`/`art` are opaque handles into our own
# server; nothing here names a site, a hoster or an upstream page.

_IDENTITY = {"id"}
_TITLE = {
    "title", "clean_title", "year", "content_type", "seasons",
    "imdb_rating", "imdb_id", "tmdb_id", "genres", "synopsis",
    "is_animated", "industry", "country", "language",
}
# Art keys are deliberately ABSENT from the v1 views below: the stored
# `poster_url` can be a scraped site's own image path, so nothing may pass it
# through. `viewer._art_pair` is the only thing that adds `poster_url` /
# `backdrop_urls` to a public response, and it adds our own handle (or a public
# CDN URL) instead. v2 shapes use `poster` / `backdrops` the same way.
_COUNTS = {"release_count", "source_count"}
# `release_id`/`work_id` are ours; they name a row, never an upstream.
_RELEASE = {
    "id", "post_id", "release_title", "season", "episode",
    "quality", "codec", "size", "languages",
}
# `kind`/`playability`/`tier` describe *our* classification of a link and are the
# axes the player ranks on; they say nothing about who hosts it. `stream_id` is
# the opaque handle the client keys on: our own row id (`link_id`, v2) is ours to
# publish, but no v1 response carries a raw ledger id any more.
_LINK = {
    "stream_id", "play_url", "link_id", "release_id", "work_id",
    "status", "state", "kind", "playability", "group", "tier",
    "playable", "downloadable", "resumable", "is_resumable", "is_temporary",
    "ephemeral", "expires_at", "protocol", "container", "content_type",
    "mime_type", "http_status", "file_size_bytes", "size_bytes",
    "rank_score", "quality_score", "latency_ms", "speed_mbps", "measured",
    "last_evidence_at", "dead",
}
VIEWS: dict[str, frozenset[str]] = {
    # GET /api/v1/posts — one list row.
    "post_brief": frozenset(_IDENTITY | _TITLE | _COUNTS),
    # GET /api/v1/posts/{id} — the same row plus its releases.
    # `option_groups` is the quality switch the player and the download card
    # read: one winner per band, each holding a projected link. It is built from
    # `project()`ed links only, and `test_redact` re-checks the finished shape.
    "post_detail": frozenset(_IDENTITY | _TITLE | {"releases", "option_groups"}),
    "release": frozenset(_RELEASE | {"sources", "links", "print_label",
                                     "band", "quality_label"}),
    "link": frozenset(_LINK),
    # The quality ladder's copy of a link: what a player or a download card needs
    # to start it, and none of the link's diagnostic furniture.
    "ladder_link": frozenset({
        "stream_id", "play_url", "kind", "playable", "status", "expires_at",
        "is_resumable", "is_temporary", "file_size_bytes", "label",
    }),
    # GET /api/v1/stats — scale, no per-site breakdown.
    "stats": frozenset({
        "posts", "releases", "sources", "active_sources", "resumable_sources",
        "temporary_sources", "works", "prints", "links", "streamable",
        "downloadable",
    }),
    # GET /api/data — the dashboard's aggregate panel.
    "dashboard_stats": frozenset({
        "sitemap_cached", "posts_count", "industry_counts", "hollywood_count",
        "bollywood_count", "anime_count", "releases_count", "sources_count",
        "active_sources", "resumable_sources", "dead_sources",
    }),
    # v2 catalogue shapes (catalog_api.py builds these by hand; scrub enforces).
    "browse_item": frozenset(_IDENTITY | {
        "title", "year", "work_type", "animated", "adult", "poster", "backdrops",
        "rating", "genres", "languages", "country", "industry", "seasons",
        "episodes", "prints", "quality_max", "best_quality_score", "available",
        "flags", "identity_suspect", "entitlement", "first_seen_at", "updated_at",
    }),
    "print": frozenset({
        "release_id", "print_id", "work_id", "print_label", "label", "coverage",
        "resolution", "quality_label", "source_tag", "codec", "bit_depth", "hdr",
        "container", "quality_score", "size_bytes", "counts", "links", "edition",
        "audio", "subtitle_mode", "details", "flags", "season_number",
        "part_number", "episode_range",
    }),
}


class ProjectionError(ValueError):
    """A view was asked for that this module does not publish."""


# The live needles, in two tiers, because detection and rewriting need different
# vocabularies:
#   _NEEDLES  — everything we can name (sites, hosters, mirrors, whatever the
#               ledger records). Used to *test* a payload: no public body may
#               contain any of these. Broad on purpose.
#   _TEXT_NEEDLES — sites and curated brands only. Used to *rewrite* a title.
#               Hoster ids stay out of it: they are strings like "example",
#               "standard", "direct", and a title cleaner that deletes English
#               words would eat the catalog, not just its provenance.
_NEEDLES: frozenset = frozenset(n for n in BASE_NEEDLES if len(n) >= 4)
_TEXT_NEEDLES: frozenset = _NEEDLES

#: A token that cannot be ordinary English: it carries a hyphen, a dot or a digit
#: ("g-direct", "v-cloud", "7starhd", "rogmovies.one"). A plain-word hoster id
#: ("standard", "example", "nexus") stays out of the *rewriting* vocabulary,
#: because a cleaner that deletes English words would eat the catalog.
_BRAND_SHAPE_RE = re.compile(r"[-.0-9]")
#: …and a token that is *entirely* a size, a resolution or a codec is not a brand,
#: however digit-shaped it looks. "1080p" and "650mb" must survive the cleaner;
#: "1XPlayer" and "7starhd" are brands that merely start with a digit, and a
#: prefix test would have protected exactly the wrong tokens.
_SIZEISH_RE = re.compile(
    r"""(?:\d+(?:[pk]|fps|hz|bit|bps|gb|mb|kb|tb|,\d+|\.\d+)"""
    r"""|\d+[xX]\d+|[hx]\.?26[45]|hevc|avc|[48]k|uhd|esub)""",
    re.IGNORECASE | re.VERBOSE)


def brand_shaped(token: str) -> bool:
    return (len(token) >= 6 and sum(c.isalpha() for c in token) >= 4
            and _BRAND_SHAPE_RE.search(token) is not None
            and _SIZEISH_RE.fullmatch(token) is None)


def set_needles(needles, text_needles=None) -> None:
    global _NEEDLES, _TEXT_NEEDLES
    broad = frozenset(str(n).lower() for n in needles
                      if n and len(str(n)) >= 4 and str(n).lower() not in GENERIC_TOKENS)
    keep = text_needles if text_needles is not None else needles
    text = frozenset(str(n).lower() for n in keep
                     if n and len(str(n)) >= 4 and str(n).lower() not in GENERIC_TOKENS)
    # Anything brand-shaped is safe to delete from display text even when the
    # conservative list did not know it: a scraper that recorded `service =
    # "g-direct"` told us a brand, not a word.
    text |= frozenset(n for n in broad if brand_shaped(n))
    _NEEDLES, _TEXT_NEEDLES = broad, text


def needles() -> frozenset:
    return _NEEDLES


def text_needles() -> frozenset:
    return _TEXT_NEEDLES


#: A trailing ``" – Some.Site"`` suffix — the shape a scraped page headline
#: ends with, whether or not that domain is in the registry yet.
_TRAILING_SOURCE_RE = re.compile(
    r"""\s*(?:[-–—|·:;,]|\band\b)\s*
        [A-Za-z0-9_.\-]*
        \.(?:fit|top|xyz|com|net|org|icu|link|buzz|click|world|hair|rich|dentist|
            press|movie|movies|shop|pro|live|today|run|cloud|drive|site|online|
            space|store|cam|band|pub|watch|stream|page|wiki|feedback|play|rest|
            society|show|email|fm|rocks|network|services|works|fun|cyou|sbs|limo)
        \s*$""",
    re.IGNORECASE | re.VERBOSE,
)
#: Anywhere in the string, a hostname — whatever the registry has or has not
#: heard of. Shape-matched on purpose: the 6.1M URLs in this ledger end in 118
#: different TLDs ("com", "io", "beer", "dad", "ist", "boats", "sbs", "cfd"…),
#: so a whitelist of known suffixes would rot the week a mirror moves — and a
#: mirror moving is exactly the event this layer has to survive silently,
#: because that is when a site name reaches a public body.
#:
#: The TLDs that actually occur in this ledger's own 6.1M recorded URLs
#: (measured, not guessed — 118 distinct suffixes, including the exotic mirrors
#: our scrapers live on: "beer", "dad", "ist", "sx", "cfd", "boats", "sbs").
#: Shape alone is not enough to call something a hostname: this catalog is full
#: of honest dotted titles — "Ra.One", "B.Tech", "C.I.Ape", "A.I.SHA My Virtual
#: Girlfriend", "BA.BL", "Mr.Fang", "U.S.A.", "Train.Dreams", "Wedding.con" — and
#: every one of them is safe here because its final segment is not a suffix any
#: registrar sells. A brand-new TLD on a *known* brand still goes: the needle and
#: the orphan-TLD rules do not care what the suffix is.
_REAL_TLDS = frozenset({
    "com", "net", "org", "in", "io", "co", "xyz", "info", "biz", "me", "tv", "cc",
    "us", "uk", "eu", "ca", "au", "de", "jp", "cn", "ru", "br", "mx", "za", "nz",
    "sg", "my", "pk", "bd", "ng", "id", "tr", "pl", "nl", "it", "es", "se", "no",
    "to", "tk", "ml", "ga", "cf", "gq", "ai", "im", "je", "gg", "sh", "ac", "ad",
    "ly", "ma", "tn", "dz", "eg", "sa", "ae", "qa", "kw", "om", "ye", "jo", "lb",
    "sy", "iq", "ir", "af", "uz", "tm", "kg", "kz", "tj", "mn", "kr", "hk", "tw",
    "th", "vn", "la", "mm", "kh", "np", "bt", "mv", "mu", "mt", "mk", "md", "ua",
    "by", "ge", "am", "az", "is", "fo", "gi", "li", "lu", "ch", "at", "be", "dk",
    "fi", "is", "ie", "pt", "gr", "hu", "cz", "sk", "si", "hr", "ba", "rs", "al",
    "ro", "bg", "cy", "lv", "lt", "ee", "fi", "site", "online", "live", "fun",
    "cloud", "link", "store", "shop", "space", "world", "click", "buzz", "top",
    "pro", "icu", "cyou", "sbs", "xyz", "beer", "dad", "ist", "sx", "cfd", "mom",
    "beauty", "vip", "pw", "ws", "cm", "download", "club", "app", "today", "study",
    "baby", "one", "wtf", "wiki", "so", "tips", "zip", "wales", "tech", "cx",
    "fit", "name", "boats", "pics", "lat", "wf", "rest", "ag", "su", "mobi",
    "email", "asia", "ink", "tc", "pm", "lol", "re", "im", "fyi", "army", "stream",
    "art", "bar", "gl", "tel", "cash", "guru", "st", "bio", "you", "yt", "be",
    "scot", "moe", "website", "company", "google", "day", "free", "sarl", "fm",
    "talk", "bike", "monster", "watch", "ngo", "dating", "zone", "menu", "hair",
    "rich", "dentist", "press", "movie", "movies", "run", "drive", "band", "pub",
    "page", "feedback", "play", "society", "show", "rocks", "network", "services",
    "works", "limo", "media", "life", "house", "shop", "blog", "dev", "xyz",
})
_DOMAIN_TLD_ALT = "|".join(sorted((re.escape(t) for t in _REAL_TLDS),
                                  key=len, reverse=True))
#: A hostname anywhere in the string. The label before the suffix needs three
#: characters, which is what keeps "Ra.One" and "Mr.Fang" (two-letter labels)
#: and "B.Tech"/"C.I.Ape" (one-letter initials) intact; the tail lookahead
#: forbids a dot as much as a letter, which is what keeps a dotted *filename*
#: whole — "The.Shadow.Effect.2017..XviD.AC3" has no segment that both reads as
#: a TLD and ends the token, so nothing is cut out of its middle.
_DOMAIN_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9._-])(?:[A-Za-z0-9_-]{1,62}\.)*"
    r"[A-Za-z][A-Za-z0-9_-]{2,62}\.(?:" + _DOMAIN_TLD_ALT + r")"
    r"(?![A-Za-z0-9_.-])", re.IGNORECASE)

_EMPTY_GROUP_RE = re.compile(r"[\[\(\{]\s*[\]\}\)]")
#: What a whole-word deletion leaves behind when the brand was a domain: the
#: registry knows "Vegamovies" and the TLD that followed it was never a word, so
#: "x264 | .is" is what survives. No honest label starts a standalone token with
#: a dot, so the fragment goes.
_ORPHAN_TLD_RE = re.compile(r"(?:^|(?<=\s))\.[A-Za-z][A-Za-z0-9]{1,11}(?=[\s&|$]|$)")
#: A scraped release label that stops describing the print and starts naming the
#: machine serving it: "Prahaar Stream Server Cineverse", "… S01E01 Server 03",
#: "… = Direct Link". Roughly 117k ledger rows are written this way, and the marker
#: word is the scraper's own, so everything from it to the end is a server
#: introduction and goes. Not at position 0: "Server" is a legitimate title, and a
#: label that *begins* with the marker names no print either way.
#:
#: This exists because an unrecognised hoster ("IQSmart", "VidZee", "Peachify") is a
#: plain English-shaped word: widening the rewriting vocabulary to delete it by shape
#: would delete honest copy as well. Cutting at the marker deletes the sentence, not
#: the language.
_SERVER_TAIL_RE = re.compile(
    r"(?<=\S)\s+(?:stream\s+(?:server|movie|link)|server\s+\d+|direct\s+links?"
    r"|all\s+direct\s+links|server\b(?=\s*$))\b.*$",
    re.IGNORECASE)
#: …and when a label is *nothing but* that introduction ("Direct Links", "Google
#: Drive", "Online Stream 2"), there is no print in it to keep: say so by returning
#: nothing, which makes the caller fall back to our own `clean_title`.
_PURE_DESCRIPTOR_RE = re.compile(
    r"^(?:(?:google\s+)?(?:drive|gdrive|g[- ]?drive)|direct\s+links?|online\s+streams?"
    r"|server\s*\d*|stream(?:\s+server)?|links?|single\s+server\s+links?"
    r"|(?:watch|play)\s+online|all\s+direct\s+links?)$",
    re.IGNORECASE)
_ORPHAN_SEP_RE = re.compile(r"\s*(?:[-–—|·:,]\s*)+(?:[-–—|·:,]\s*)+")


def _decode_entities(text: str) -> str:
    """Resolve HTML character references before anything else looks at the string.

    A stored title is whatever the site's page said, and a page says an apostrophe
    as ``&#8217;`` and a dash as ``&ndash;``. Decoding is the difference between
    serving ``JoJo&#8217;s Bizarre Adventure`` and serving the title.

    Run twice on purpose: a CMS that escaped its own escapes answers
    ``&amp;#8217;``, which becomes a readable ``&#8217;`` on the first pass and only
    resolves on the second. Two passes is the bound — an input built as a long
    ``&amp;amp;amp;…`` chain would otherwise make this loop as many times as the
    caller's patience allows.

    ``&nbsp;`` decodes to U+00A0, a space nothing else here treats as one, so it is
    folded to an ordinary space in the same breath.
    """
    if "&" not in text:
        return text
    return html.unescape(html.unescape(text)).replace("\xa0", " ")

#: A deletion must not leave the reader staring at a hole. Once the brand is
#: gone, a connective that now points at nothing ("… links Free on",
#: "उपलब्ध सिर्फ़ पर") is the last visible trace of the sentence we removed — and a
#: naked eye that spots one starts looking for the rest. Only words that cannot
#: *end* a noun phrase are peeled: prepositions, articles, copulas, case
#: markers. Nouns and adjectives are never in this list, so "Rush Hour",
#: "Game Over", "Check In", "…: The Movie" and "Free" keep their last word.
_DANGLING_CONNECTIVES = frozenset({
    "on", "at", "by", "for", "of", "to", "and", "or", "but", "nor", "the", "a",
    "an", "is", "are", "was", "were", "be", "been", "with", "from", "than",
    "per", "via", "into", "onto", "towards", "upon",
    # Devanagari postpositions and case markers — the Hindi scrapers' blurbs are
    # the bulk of this catalog and they hang together the same way.
    "पर", "में", "से", "के", "की", "का", "को", "लिए", "सिर्फ़", "सर्फ", "और", "एक",
    "तक", "अपनी", "वाला", "वाली", "है", "हूँ",
})
#: …and the same word sitting just before a separator instead of at the end.
_DANGLING_BEFORE_SEP_RE = re.compile(
    r"\b(?:" + "|".join(sorted((re.escape(w) for w in _DANGLING_CONNECTIVES),
                               key=len, reverse=True)) + r")\s*(?=[|·])")
#: Punctuation standing alone after a space is the corpse of a deleted brand
#: ("… Free on ."); punctuation glued to a word belongs to that word ("Inc.",
#: "What?!", "(2024)"). Only the detached kind is peeled.
_DETACHED_TAIL_PUNCT_RE = re.compile(r"\s+[.,;:·\-–—|&]+\s*$")


def _peel_dangling(text: str) -> str:
    """Drop connectives that lost the thing they pointed at.

    Two positions matter: at the very end of the string, where a trailing
    connective is the corpse of the sentence the brand lived in, and immediately
    before a separator, which is where the scraped Hindi blurbs put their hole
    ("… उपलब्ध सिर्फ़ पर | Dual Audio").

    Punctuation a peel did not touch is kept — "Kidnapping Inc." and "C.I.D."
    need their final dot, and a cleaner that amputates it is damaging the copy
    rather than protecting anyone. Brackets are never peeled either: "(2024)"
    is a balanced part of a title."""
    out = text
    while True:
        core = out.rstrip()
        cut = _DETACHED_TAIL_PUNCT_RE.sub("", core)
        if cut != core:
            out = cut
            continue
        tokens = core.split()
        if not tokens:
            return ""
        # A one-word string is a title, not a fragment: "From", "Is", "Server"
        # are all real catalog titles, and 41 of them were being emptied before
        # this line existed. Only a connective that has a title behind it dangles.
        if len(tokens) == 1:
            return core
        if tokens[-1].lower() in _DANGLING_CONNECTIVES:
            out = core[:len(core) - len(tokens[-1])]
            continue
        peeled = re.sub(r"\s{2,}", " ", _DANGLING_BEFORE_SEP_RE.sub("", core))
        if peeled == core:
            return core
        out = peeled


def _drop_needles(text: str) -> str:
    """Delete known site/brand tokens from display text.

    Whole-word first, because the needle list contains mirror TLDs: a substring
    match on "bond" would eat "Bondi Banks". Then whole *word-chunks*: a scraped
    headline glues the brand to a label ("OfficialRogmovies", "HDHub4uIndia"),
    and a chunk like that is a brand compound, not a word a viewer needs. A chunk
    is only dropped when a brand is inside it and the chunk is short enough to be
    one name rather than a sentence."""
    out = text
    for needle in sorted(_TEXT_NEEDLES, key=len, reverse=True):
        if needle not in out.lower():
            continue
        out = re.sub(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", "",
                     out, flags=re.IGNORECASE)
    glued = frozenset(n for n in _TEXT_NEEDLES if len(n) >= 5)
    if glued:
        kept = []
        for word in out.split():
            core = word.strip("()[]{}<>\"',.;:!?|·-–—&").lower()
            if len(core) <= 40 and any(n in core for n in glued):
                continue
            kept.append(word)
        out = " ".join(kept)
    return re.sub(r"\s{2,}", " ", out)


def scrub_text(value) -> str:
    """Remove every *known* site/brand token from one display string.

    Deliberately not clever: it deletes whole-word tokens the needle list
    recognises, and trailing ``" – Some.Site"`` suffixes that end in a real
    registrable TLD. Guessing at an unknown brand from its shape would eat
    honest labels ("– Part 2", "{Hindi – Amazon Prime}"), so an unrecognised
    brand survives here and is reported by ``test_redact``'s residual scan
    instead — which is how the curated list grows. Anything the UI actually
    renders should come from :func:`public_label`, which is built from
    structured columns and cannot name a source at all.

    The ledger keeps the original text untouched: this is a rendering decision
    at the edge, never a rewrite of stored data."""
    text = str(value if value is not None else "")
    if not text:
        return ""
    out = _decode_entities(text)
    # Checked before the cut as well as after it: "All Direct Links" would
    # otherwise leave the orphan word "All" standing where a label used to be.
    if len(out.split()) > 1 and _PURE_DESCRIPTOR_RE.match(out):
        return ""
    out = _SERVER_TAIL_RE.sub("", out)
    out = _DOMAIN_TOKEN_RE.sub(" ", out)
    out = _drop_needles(out)
    out = _TRAILING_SOURCE_RE.sub("", out)
    out = _ORPHAN_TLD_RE.sub("", out)
    out = _drop_needles(out)
    out = _EMPTY_GROUP_RE.sub("", out)
    out = _ORPHAN_SEP_RE.sub(" · ", out)
    out = re.sub(r"\s{2,}", " ", out)
    out = out.strip(" \t-–—|·:,>&")
    out = re.sub(r"^[:·\-–—\s]+", "", out)
    out = _peel_dangling(out)
    # A label that is only the server introduction is no label at all — but a
    # one-word title ("Server", "Direct") is a title, so only a multi-word
    # remainder is treated as a descriptor.
    if len(text.split()) > 1 and _PURE_DESCRIPTOR_RE.match(out):
        return ""
    # Empty is honest. Returning the original because cleaning left nothing would
    # put the brand we just deleted back on the screen; the caller has its own
    # `clean_title` to fall back on.
    return out.strip()


def public_label(release, title=None) -> str | None:
    """A provenance-free name for one print, built from structured columns.

    Netflix shows "HD · 5.1" rather than the file's headline; we have the same
    columns (`quality`, `codec`, `size`, `languages`, `season`, `episode`), so
    the user gets an honest label and the scraper's brand suffix never appears.
    """
    row = release if isinstance(release, dict) else dict(release)
    parts = []
    season = str(row.get("season") or "").strip()
    episode = str(row.get("episode") or "").strip()
    if season and episode:
        parts.append(f"{season.upper()} {episode.upper()}")
    elif season:
        parts.append(season.upper() if season.upper().startswith("S") else f"Season {season}")
    elif episode:
        parts.append(episode.upper())
    quality = str(row.get("quality") or "").strip()
    codec = str(row.get("codec") or "").strip()
    rung = " ".join(x for x in (quality, codec) if x)
    if rung:
        parts.append(rung)
    audio = str(row.get("languages") or "").strip()
    if audio:
        parts.append(audio)
    size = str(row.get("size") or "").strip()
    if size:
        parts.append(size)
    label = " · ".join(parts).strip(" ·")
    if not label:
        raw = row.get("release_title") or row.get("print_label")
        return scrub_text(raw) if raw else None
    return scrub_text(label)


#: Placeholder words our own scrapers store when a field was blank upstream.
#: They are not provenance, but they are not a genre either, and a card that
#: reads "Unknown" next to the title is worse than one that reads nothing.
_BLANK_TOKENS = frozenset({"unknown", "none", "null", "n/a", "other", "-"})
#: What a genre/`--`language list really contains. Some parsers mistook a page's
#: schema.org + WordPress block for the genre list, so these tokens — plus
#: anything with a digit, an underscore or a domain in it — are markup residue,
#: not a category, and a chip that says `wp-content` tells the user we are a
#: scraper rather than a product.
_JUNK_TOKENS = frozenset({
    "author", "authors", "avatar", "avatars", "uploads", "upload", "wp-content",
    "wp-json", "wp-includes", "name", "url", "image", "images", "item", "items",
    "position", "listitem", "list", "itemlist", "webpage", "website", "breadcrumb",
    "breadcrumbs", "graph", "@graph", "feed", "comment", "comments", "embed",
    "iframe", "src", "href", "id", "class", "style", "script", "div", "span",
    "page", "pages", "date", "time", "type", "kind", "site", "sites", "home",
})
#: A category label: letters and the punctuation genre names actually use
#: ("Sci-Fi", "Action & Adventure"). No digits, no dots — a dot is a domain, and
#: `image.tmdb.org` is not a genre however the scraper filed it. At most one hyphen:
#: "Sci-Fi" is a genre, "download-white-punjab-2023-480p" is a page slug.
_CATEGORY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9 '&/()\-]*$")
#: `genre`/`language` chips are decoration; the first few carry the meaning.
MAX_LIST_TOKENS = 12
LIST_KEYS = frozenset({"genres", "language", "languages", "country", "industry"})
_MARKUP_RE = re.compile(r"[{}\"\\]|://|@type|<[^>]*>")


def _category_token(raw) -> str | None:
    """One list element, kept only if it could plausibly be a category name."""
    if isinstance(raw, bool) or not isinstance(raw, (str, int, float)):
        return None
    text = str(raw)
    if _MARKUP_RE.search(text):
        return None
    token = scrub_text(text).strip(" .,:;·-–—|&\"'()")
    if not (2 <= len(token) <= 40) or not _CATEGORY_RE.match(token):
        return None
    if token.count("-") > 1:                       # a page slug, not a genre
        return None
    if token.lower() in _BLANK_TOKENS or token.lower() in _JUNK_TOKENS:
        return None
    return token


def public_list(value) -> str:
    """One stored list-field as the public may see it: real categories only.

    Cleans element by element and re-emits the same JSON shape the client already
    parses; the ledger keeps the raw string, so nothing is lost, only
    un-displayed."""
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    try:
        items = json.loads(text)
    except (ValueError, TypeError):
        items = None
    if not isinstance(items, list):
        return scrub_text(text)
    return json.dumps(_clean_tokens(items), ensure_ascii=False)


def project(row, view: str) -> dict:
    """Allowlist one row/dict into `view`. Unknown keys are dropped silently:
    that is the point. A view name that is not published raises."""
    allowed = VIEWS.get(view)
    if allowed is None:
        raise ProjectionError(f"unpublished view: {view!r}")
    src = row if isinstance(row, dict) else dict(row)
    out = {}
    for key, value in src.items():
        if key not in allowed:
            continue
        if key in LIST_KEYS and isinstance(value, str):
            value = public_list(value)
        elif key in TEXT_KEYS and isinstance(value, str):
            value = scrub_text(value)
        out[key] = value
    leaked = set(out) & PROVENANCE
    if leaked:
        # Unreachable while the allowlists are reviewed; loud if someone edits
        # one without reading this file.
        raise ProjectionError(f"view {view!r} publishes provenance: {sorted(leaked)}")
    return out


def project_many(rows, view: str) -> list[dict]:
    return [project(row, view) for row in rows]


def scrub(obj):
    """Recursively drop every PROVENANCE key from a hand-built tree (and clean
    every free-text value in it).

    Returns new containers, so the caller's own copy of the data — which may
    legitimately still hold provenance for internal use — is never mutated."""
    if isinstance(obj, dict):
        out = {}
        for key, value in obj.items():
            if key in PROVENANCE:
                continue
            if key in LIST_KEYS:
                out[key] = (_clean_tokens(value) if isinstance(value, (list, tuple))
                            else public_list(value))
                continue
            out[key] = (scrub_text(value) if key in TEXT_KEYS and isinstance(value, str)
                        else scrub(value))
        return out
    if isinstance(obj, (list, tuple)):
        return [scrub(v) for v in obj]
    return obj


def _clean_tokens(items) -> list[str]:
    """Already-parsed list (a v2 shape): real categories, first-seen casing,
    in order, capped — a card shows a handful of chips, not a keyword dump."""
    seen: dict[str, str] = {}
    for item in items:
        token = _category_token(item)
        if token:
            seen.setdefault(token.lower(), token)
    return list(seen.values())[:MAX_LIST_TOKENS]


def provenance_keys(obj, found=None) -> list[str]:
    """Every PROVENANCE key name anywhere in a tree — the structural half of the
    guarantee, independent of any allowlist."""
    seen = found if found is not None else []
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in PROVENANCE:
                seen.append(str(key))
            provenance_keys(value, seen)
    elif isinstance(obj, (list, tuple)):
        for value in obj:
            provenance_keys(value, seen)
    return seen


#: Keys whose values are handles we minted (`mint_token`/`mint_text`): base64
#: noise, not information about anyone. A sentinel scan masks these before reading
#: text, because random noise collides with brand spellings.
MINTED_KEYS = frozenset({"stream_id", "art", "play_url", "download_url",
                         "link_ref", "work_ref", "backup_handles"})


def minted_values(obj, found=None) -> list[str]:
    """Every opaque handle in `obj`, so a scan can mask it before reading text.

    A `stream_id` is base64 noise, and noise collides: across a 560-post sample of
    the real catalog, the only way our own sentinel found a "site name" inside the
    quality ladder was a handle that happened to spell `gmpg` or `send`. Masking
    the handles keeps a real brand in a label visible while stopping the scan from
    crying wolf — and a handle is by construction not information about anyone.
    """
    seen = found if found is not None else []
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in MINTED_KEYS:
                if isinstance(value, str) and len(value) >= 4:
                    seen.append(value)
                elif isinstance(value, (list, tuple)):
                    seen.extend(str(item) for item in value
                                if isinstance(item, str) and len(item) >= 4)
            else:
                minted_values(value, seen)
    elif isinstance(obj, (list, tuple)):
        for value in obj:
            minted_values(value, seen)
    return seen


def is_clean(obj, needles=None) -> list[str]:
    """Every provenance leak found in `obj`: forbidden key names, then known
    site/brand tokens anywhere in the serialised text. Empty list means clean.

    Opaque handles we minted are masked out first (see :func:`minted_values`);
    everything else is scanned as written."""
    bad = list(dict.fromkeys(provenance_keys(obj)))
    text = json.dumps(obj, ensure_ascii=False, default=str).lower()
    for value in dict.fromkeys(minted_values(obj)):
        text = text.replace(value.lower(), "<id>")
    for n in (needles if needles is not None else _NEEDLES):
        token = str(n).lower()
        if len(token) >= 4 and token in text:
            bad.append(token)
    return bad


def assert_clean(payload, needles=None) -> None:
    bad = is_clean(payload, needles)
    if bad:
        raise AssertionError(f"public payload contains provenance tokens: {sorted(bad)}")


# ── opaque handles ───────────────────────────────────────────────────────────
#
# A public response used to hand out `download_sources.id` next to
# `service`+`resource_id`, i.e. a stable primary key a third party could mirror
# as their own catalog id. `stream_id`/`art` replace it with a signed, opaque,
# reversible token: ours to mint, meaningless to everyone else, and tampering
# with one fails instead of resolving someone else's row.
#
# This is obfuscation, not authorisation — the route stays unauthenticated
# because the product is an unauthenticated catalog. It buys two real things:
# no stable upstream-shaped identifier in public, and no way to enumerate or
# forge ids without the secret.

_TOKEN_VERSION = 1


def _keystream(secret: str, n: int, salt: str) -> bytes:
    out = b""
    counter = 0
    key = secret.encode("utf-8")
    while len(out) < n:
        out += hashlib.sha256(
            key + salt.encode("utf-8") + struct.pack(">I", counter)).digest()
        counter += 1
    return out[:n]


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(token: str) -> bytes | None:
    if not isinstance(token, str) or not token:
        return None
    try:
        return base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
    except Exception:
        return None


def mint_token(number: int, secret: str) -> str:
    """Sign one of our own integer row ids into an opaque public handle."""
    raw = struct.pack(">q", int(number))
    body = bytes(a ^ b for a, b in zip(raw, _keystream(secret, len(raw), "id")))
    tag = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()[:4]
    return _b64(bytes([_TOKEN_VERSION]) + body + tag)


def parse_token(token, secret: str, signed_only: bool = False) -> int | None:
    """Inverse of :func:`mint_token`; ``None`` for anything not minted by us.

    A plain integer is accepted unless ``signed_only``: the v1 field apps already
    key on row ids, so the route must keep serving them while the client moves to
    tokens. But a row id is *enumerable* — walking 1..3,070,247 would harvest
    every file URL we hold without our API ever naming a hoster — so the public
    port takes handles only, and the plain form survives on loopback for the
    operator's own curl and healing scripts."""
    if isinstance(token, int):
        return token if not signed_only else None
    text = str(token or "").strip()
    if not text:
        return None
    if text.isdigit():
        return None if signed_only else int(text)
    data = _unb64(text)
    if data is None or len(data) < 9 or data[0] != _TOKEN_VERSION:
        return None
    body, tag = data[1:-4], data[-4:]
    want = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()[:4]
    if not hmac.compare_digest(tag, want):
        return None
    raw = bytes(a ^ b for a, b in zip(body, _keystream(secret, len(body), "id")))
    return int(struct.unpack(">q", raw)[0])


_VIP_PASS_VERSION = 3


def mint_vip_pass(expires_at: float, secret: str) -> str:
    """Sign an expiry instant into a compact VIP pass handle.

    A pass is a capability, not an account: whoever holds it is treated as VIP
    until the signed instant. It carries no user id, price or payment detail, so
    a leaked pass reveals nothing — and because there is no revocation list, the
    only way to end one early is to rotate the signing secret.
    """
    body = struct.pack(">q", int(expires_at))
    tag = hmac.new(secret.encode("utf-8"), b"vip" + body,
                   hashlib.sha256).digest()[:8]
    return _b64(bytes([_VIP_PASS_VERSION]) + body + tag)


def parse_vip_pass(token, secret: str, now: float | None = None) -> float | None:
    """The expiry a pass was minted for, or ``None`` for anything not ours,
    tampered with, or already lapsed. A capability check, never an account."""
    data = _unb64(str(token or ""))
    if data is None or len(data) != 1 + 8 + 8 or data[0] != _VIP_PASS_VERSION:
        return None
    body, tag = data[1:9], data[9:]
    want = hmac.new(secret.encode("utf-8"), b"vip" + body,
                    hashlib.sha256).digest()[:8]
    if not hmac.compare_digest(tag, want):
        return None
    expires_at = float(struct.unpack(">q", body)[0])
    moment = time.time() if now is None else float(now)
    return expires_at if expires_at > moment else None


def mint_text(value: str, secret: str) -> str:
    """Opaque, reversible handle for a string (an art URL that has no row id)."""
    raw = value.encode("utf-8")
    body = bytes(a ^ b for a, b in zip(raw, _keystream(secret, len(raw), "txt")))
    tag = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()[:4]
    return _b64(bytes([_TOKEN_VERSION + 128]) + struct.pack(">H", len(raw)) + body + tag)


def parse_text(token, secret: str) -> str | None:
    data = _unb64(str(token or ""))
    if data is None or len(data) < 4 or data[0] != _TOKEN_VERSION + 128:
        return None
    size = struct.unpack(">H", data[1:3])[0]
    body, tag = data[3:-4], data[-4:]
    if len(body) != size:
        return None
    if not hmac.compare_digest(tag, hmac.new(secret.encode("utf-8"), body,
                                             hashlib.sha256).digest()[:4]):
        return None
    raw = bytes(a ^ b for a, b in zip(body, _keystream(secret, len(body), "txt")))
    return raw.decode("utf-8", "replace")


def stream_secret(db_path=None) -> str:
    """Per-install signing secret, persisted beside the catalog.

    Read from ``RADD_STREAM_SECRET`` when set (deployment owns it); otherwise a
    random one is generated into ``server_state`` so tokens stay stable across
    restarts. Never in the checkout, never in the git history."""
    env = os.environ.get("RADD_STREAM_SECRET")
    if env:
        return env
    if db_path is None:
        return "radd-stream-dev-secret-unconfigured"
    path = Path(db_path)
    if not path.exists():
        return "radd-stream-dev-secret-unconfigured"
    try:
        conn = sqlite3.connect(path)
        try:
            conn.execute("CREATE TABLE IF NOT EXISTS server_state "
                         "(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            row = conn.execute("SELECT value FROM server_state WHERE key = "
                               "'stream_secret'").fetchone()
            if row:
                return row[0]
            secret = base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")
            conn.execute("INSERT INTO server_state(key, value) VALUES(?, ?)",
                         ("stream_secret", secret))
            conn.commit()
            return secret
        finally:
            conn.close()
    except Exception:
        return "radd-stream-dev-secret-unconfigured"


# ── art: keep the image host ours ────────────────────────────────────────────

#: Both tables that can hold artwork, keyed by the `t=` query parameter a client
#: may pass. Nothing else is resolvable, so the redirector cannot be aimed at an
#: arbitrary table.
ART_TABLES = {"posts": "posts", "works": "cat_works"}


def art_ref(target_id, secret: str, base_url: str, kind: str = "poster",
            index: int = 0, table: str = "posts") -> str:
    """Public URL for a work's artwork: our host plus an opaque handle.

    Art is served by 302 like the stream route — no bytes cross this VM, no
    upstream host appears in the interface."""
    scope = "" if table == "posts" else f"&t={table}"
    return (f"{base_url.rstrip('/')}/api/v1/art?id={mint_token(target_id, secret)}"
            f"&k={kind}&n={index}{scope}")


def public_image_value(url) -> str | None:
    """The URL itself when its host is a third-party art CDN we may name.

    This is the only shape a season poster or an episode still may leave this box
    in: those rows are never routed through ``/api/v1/art`` (that redirector
    resolves a *work's* poster), so a non-public image URL is dropped rather than
    handed out. The scan is the same one :func:`public_art_value` uses."""
    text = str(url or "").strip()
    if not text:
        return None
    host = text.split("//", 1)[-1].split("/", 1)[0].split("@")[-1].lower()
    host = host.split(":", 1)[0]
    return text if host in PUBLIC_IMAGE_HOSTS else None


def public_art_value(url, post_id, secret: str, base_url: str,
                     kind: str = "poster", index: int = 0, table: str = "posts"):
    """Rewrite one stored image URL for public consumption.

    Art already on a public CDN is handed out directly (it names nothing about
    us or our sources); art hosted by a site we scrape becomes an ``art_ref``.
    With no base URL known (an offline test, a request without a Host header)
    the handle is root-relative, which every same-origin consumer resolves."""
    direct = public_image_value(url)
    if direct is not None:
        return direct
    text = str(url or "").strip()
    if not text:
        return None
    scope = "" if table == "posts" else f"&t={table}"
    if not base_url:
        return (f"/api/v1/art?id={mint_token(post_id, secret)}"
                f"&k={kind}&n={index}{scope}")
    return art_ref(post_id, secret, base_url, kind=kind, index=index, table=table)


def art_url_for(post_id: int, kind: str, index: int, db_path,
                table: str = "posts") -> str | None:
    """Resolve our own artwork handle back to the stored image URL.

    Internal by design: only the redirector calls it, only on the machine that
    holds the ledger."""
    from_table = ART_TABLES.get(str(table or "posts"), "posts")
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(f"SELECT poster_url, backdrop_urls FROM {from_table} "
                               "WHERE id = ?", (post_id,)).fetchone()
        except sqlite3.Error:
            return None
    if row is None:
        return None
    if kind == "poster":
        return row["poster_url"] or None
    if kind == "backdrop":
        raw = row["backdrop_urls"]
        try:
            items = json.loads(raw) if raw else []
        except Exception:
            items = [u for u in re.split(r"[,\s]+", str(raw or "")) if u.startswith("http")]
        if isinstance(items, list) and 0 <= index < len(items):
            return items[index] or None
    return None


def art_is_adult(target_id: int, db_path, table: str = "posts") -> bool:
    """Adult rule for the artwork redirector, in whichever table the art lives."""
    from_table = ART_TABLES.get(str(table or "posts"), "posts")
    with sqlite3.connect(db_path) as conn:
        try:
            row = conn.execute(f"SELECT is_18_plus FROM {from_table} WHERE id = ?",
                               (target_id,)).fetchone()
        except sqlite3.Error:
            return True          # unknown table or vanished row: show nothing
    return bool(row and row[0])


def adult_clause(alias: str = "posts") -> str:
    """The one adult rule, shared by every public emitter (same predicate the
    v2 read layer and the ledger views already use)."""
    return f"({alias}.is_18_plus IS NULL OR {alias}.is_18_plus = 0)"


def link_is_adult(source_id: int, db_path) -> bool:
    """Adult rule for the stream redirector, walking link → release → post.

    Every list route hides a flagged title, but a redirector addressed by a bare
    link id never sees the list: without this, the play route alone would be an
    adult viewer. An unknown link answers True too, so a vanished row, a typo and
    a flagged title are indistinguishable — and none of them plays."""
    with sqlite3.connect(db_path) as conn:
        try:
            row = conn.execute(
                """
                SELECT p.is_18_plus FROM download_sources s
                JOIN releases r ON r.id = s.release_id
                JOIN posts p ON p.id = r.post_id
                WHERE s.id = ?
                """, (source_id,)).fetchone()
        except sqlite3.Error:
            return True
    return bool(row and row[0])


# ── rate limiting: the documented buckets, in-app ────────────────────────────
#
# API_V2.md §16.5 specifies the header triple and the per-bucket budgets; the
# plan was "proxy first, in-app second", and the VM has no proxy in front of
# every route, so the numbers land here. Token bucket per client IP, in-memory:
# a restart is a reset, which is the right failure mode for a catalog that is
# public anyway.

BUCKET_LIMITS = {
    "play": (30, 60.0),      # /stream, /art, /m3u — the expensive ones
    "browse": (60, 60.0),    # /posts, /api/data, search, sitemap
    "reports": (10, 60.0),   # /stats
    "account": (30, 60.0),   # /api/v2/account* — cheap calls, but they carry a key
}

#: The budget for a bucket name nobody declared. An unmapped route must still be
#: throttled (§16.5), so it pays into these numbers rather than into none.
DEFAULT_BUCKET = (60, 60.0)


class RateLimiter:
    def __init__(self, limits=None):
        self.limits = dict(BUCKET_LIMITS)
        if limits:
            self.limits.update(limits)
        self._buckets: dict[tuple[str, str], tuple[float, float]] = {}

    def check(self, bucket: str, client: str, moment: float | None = None) -> dict:
        """Consume one unit. Returns the IETF RateLimit-* triple plus `allowed`."""
        now = time.time() if moment is None else moment
        left, opened, limit, window = self.state(bucket, client, now)
        if left < 1:
            reset = max(0.0, window - (now - opened))
            return {"allowed": False, "limit": limit, "remaining": 0,
                    "reset": int(round(reset)), "retry_after": int(round(reset)) or 1}
        self._buckets[(bucket, client or "?")] = (left - 1.0, opened)
        if len(self._buckets) > 4096:      # a page of dead visitors must not grow RAM
            self._buckets = {k: v for k, v in self._buckets.items() if now - v[1] < window}
        reset = int(round(window - (now - opened)))
        return {"allowed": True, "limit": limit, "remaining": int(left - 1),
                "reset": max(0, reset)}

    def state(self, bucket: str, client: str, moment: float | None = None) -> tuple:
        """The bucket's live ``(left, opened, limit, window)`` without spending it.

        Refilling a window that has aged out is the same pure read `check()` does
        first, so a peek is never staler than the answer it mirrors."""
        limit, window = self.limits.get(bucket, DEFAULT_BUCKET)
        now = time.time() if moment is None else moment
        left, opened = self._buckets.get((bucket, client or "?"), (float(limit), now))
        if now - opened >= window:
            return float(limit), now, limit, window
        return left, opened, limit, window

    def peek(self, bucket: str, client: str, moment: float | None = None) -> dict:
        """Read the budget a caller has left.

        `check()` is the one place a token is spent, and the HTTP host spends it
        once per request; a route that needed the numbers for its own headers had
        to be able to ask without paying again, or every budget would halve and
        this module would hold two views of one bucket."""
        now = time.time() if moment is None else moment
        left, opened, limit, window = self.state(bucket, client, now)
        return {"allowed": left >= 1, "limit": limit,
                "remaining": max(0, int(left)),
                "reset": max(0, int(round(window - (now - opened))))}

    def headers(self, verdict: dict) -> list[tuple[str, str]]:
        return [("RateLimit-Limit", str(verdict["limit"])),
                ("RateLimit-Remaining", str(verdict["remaining"])),
                ("RateLimit-Reset", str(verdict["reset"]))]


limiter = RateLimiter()


def client_ip(handler) -> str:
    """Forwarded-for first, then the socket peer; XFF is only trusted here
    because the response carries no secret and the limit is advisory."""
    forwarded = str(handler.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
    if forwarded:
        return forwarded
    return str(getattr(handler, "client_address", ("",))[0] or "")


# ── needles for the tests ────────────────────────────────────────────────────

def site_needles(db_path=None) -> frozenset[str]:
    """Every provenance token we can name: the frozen baseline, the domain
    registry, and whatever the live ledger records. For *detection*."""
    needles = set(BASE_NEEDLES)
    needles.update(_registry_needles())
    if db_path and Path(db_path).exists():
        try:
            with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
                has_cat_sites = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='cat_work_sites'"
                ).fetchone()
                if has_cat_sites:
                    for (value,) in conn.execute("SELECT DISTINCT source_site FROM cat_work_sites"):
                        needles.add(str(value or "").strip().lower())
                else:
                    for (value,) in conn.execute("SELECT DISTINCT source_site FROM posts"):
                        needles.add(str(value or "").strip().lower())
                # For download_sources, scan when table is small or indexed; _registry_needles()
                # already carries all canonical hosters and services.
                has_service_idx = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='index' AND tbl_name='download_sources' AND name='idx_sources_service'"
                ).fetchone()
                sub_cnt = conn.execute("SELECT count(*) FROM (SELECT 1 FROM download_sources LIMIT 100000)").fetchone()[0]
                if has_service_idx or sub_cnt < 100000:
                    for (value,) in conn.execute("SELECT DISTINCT service FROM download_sources"):
                        needles.add(str(value or "").strip().lower())
                    for (value,) in conn.execute(
                            "SELECT DISTINCT source_name FROM download_sources"):
                        head = re.match(r"\W*([A-Za-z][A-Za-z0-9\-]{4,})", str(value or ""))
                        if head:
                            needles.add(head.group(1).lower())
        except Exception:
            pass
    return frozenset(
        n for n in needles
        if n and len(n) >= 4 and n not in {"unknown", "null", "none"}
        and n not in GENERIC_TOKENS)


#: `posts.source_site` also holds the literal 'vegamovies' as a schema default on
#: rows we could not attribute; that value is our own, not a claim about a title.
UNATTRIBUTED = "vegamovies"


def site_text_needles(db_path=None) -> frozenset[str]:
    """The conservative vocabulary for *rewriting* display text: the sites we
    scrape, their mirror domains, and the curated brand list — never a hoster
    identifier, which is too close to ordinary English."""
    needles = set(BASE_NEEDLES)
    needles.update(_registry_needles())
    if db_path and Path(db_path).exists():
        try:
            with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
                for (value,) in conn.execute("SELECT DISTINCT source_site FROM posts"):
                    text = str(value or "").strip().lower()
                    if text and text != UNATTRIBUTED:
                        needles.add(text)
        except Exception:
            pass
    return frozenset(
        n for n in needles
        if n and len(n) >= 4 and n not in {"unknown", "null", "none"}
        and n not in GENERIC_TOKENS)


def _registry_needles() -> set:
    needles = set()
    registry = Path(__file__).with_name("domain_registry.json")
    if registry.exists():
        try:
            data = json.loads(registry.read_text(encoding="utf-8"))
            for name, entry in (data.get("sites") or {}).items():
                needles.add(str(name).lower())
                for mirror in entry.get("known_mirrors") or []:
                    host = str(mirror).split("//", 1)[-1].split("/", 1)[0].lower()
                    if "." in host:
                        # the full domain and its brand label — never the bare
                        # TLD, which is an ordinary English word ("bond", "rich")
                        needles.add(host)
                        needles.add(host.rsplit(".", 2)[-2] if host.count(".") >= 2
                                    else host.split(".", 1)[0])
        except Exception:
            pass
    return needles


# ---------------------------------------------------------------------------
# Cross-origin policy: the other half of the same rule
# ---------------------------------------------------------------------------

#: CORS, per API_V2.md §16.7: an explicit allow-list, never `*`. A wildcard let any
#: website read the catalog straight from a visitor's browser and re-publish it — the
#: exact "other person uses our API in their own app" hole the owner ruled out. Our real
#: clients need nothing here: the Android app is a native HTTP client that sends no
#: `Origin`, and the dashboard is served by this same origin. Add an exact origin to this
#: set only when a third-party web client is authorised.
CORS_ALLOW_ORIGINS: frozenset[str] = frozenset()


def cors_headers_for(origin: str) -> list[tuple[str, str]]:
    """The two headers that make one allow-listed browser origin happy, or none.

    A refused origin gets no header at all, so the browser blocks it and our answer is
    carried by absence — the same trick the adult rule uses for a 404.
    """
    if origin and origin in CORS_ALLOW_ORIGINS:
        return [("Access-Control-Allow-Origin", origin), ("Vary", "Origin")]
    return []
