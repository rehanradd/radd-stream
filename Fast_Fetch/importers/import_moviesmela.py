#!/usr/bin/env python3
"""
import_moviesmela.py — isolated staging importer for https://www.moviesmela.com

Writes ONLY to /home/ubuntu/radd-stream-data/moviesmela.db. Never touches the
production catalog; merge with Fast_Fetch/merge_catalogs.py after operator
review. Pure Python standard library. Zero pip packages.

WHAT THIS SITE IS, MEASURED LIVE 2026-10-28 (owner and this agent probed it
independently and agree):

    WordPress with an open REST API. 20,888 posts, X-WP-TotalPages 1,045 at
    per_page=20. `GET /wp-json/wp/v2/posts?per_page=20&page=N` answers in
    ~0.6-1.2 s and carries everything the crawler needs, including
    `content.rendered`. `&_embed=1` at per_page=20 answers
    `200 + content-length: 0` (measured, twice) — the response is silently
    truncated, so this module never asks for `_embed` and resolves taxonomy
    names from a one-time /wp-json/wp/v2/categories map instead.

    One post == one watchable page == one movie, one episode, or one whole
    season bundle. 820 consecutive posts sampled: every single one carries
    2-4 `<iframe>` players and NOTHING else — no `<video>`, no `.m3u8`, no
    download anchor, no external `<a>`. The players observed, with their
    counts out of those 820 posts:

        mxdrop.to/e/<token>          819   (MDCore/videojs, 302 to mxdrop.top)
        pkembed.site/embed-<t>.html  814   (FluidPlayer/videojs)
        do7go.com/e/<token>          811   (403 from this host)
        ok.ru/videoembed/<id>        653   (Odnoklassniki)
        pkembed.online, embedpk.net, playmogo.com, myvidplay.com, dsvplay.com  rare

PLAYABILITY — READ THIS BEFORE COUNTING ANY ROW.
Every object the page itself exposes is an iframe of a third-party player;
there is no byte endpoint on the page. The Android client has no WebView escape
hatch (PlaybackRecovery.kt / LinkClassification.kt send Playability.WEBVIEW to
"Not playable here", and viewer.py maps playback_type 'iframe' -> kind
'external' -> playable=false), so an iframe row is stored as
`playback_type='iframe'` with `status='unverified'`: catalog evidence, never a
watchable link.

Two of those hosts, however, answer a pure-stdlib request chain with a real
byte endpoint, verified live on 2026-10-28 (owner and this agent independently,
on six posts each): mxdrop (`MDCore.wurl` after unpacking the page's packed
config in base 10) and pkembed (the same packer in base 36, publishing
`<source src=…/l.mp4?t=…>` renditions on `plusN.vkpluscdn.site` or
`stoplus.vkcdn5.com`). pkembed is the site's dominant player — 100 of the newest
100 posts carry one — so this is not a marginal path.
For those rows only, this importer stores `playback_type='url'` — which
viewer.py maps to kind 'resolve', i.e. the JIT path — with `is_temporary=1`
because the endpoint is signed and short-lived. The stored `source_url` is
still the EMBED URL: mxdrop's signature expires in about six hours and
pkembed's in twelve (`s` plus an `e=43200` lifetime), so a persisted mp4 URL is
a 403 by tomorrow and a lie about what the catalog holds. `status='active` is
set only when an import-time probe actually got `206 video/mp4`; with the
default (no `--probe`) crawl every resolvable row is `unverified`, and
`raw_meta` says why. The unpacking lives in importers/host_resolvers.py;
nothing in this module pretends a filemoon or do7go iframe is playable.
`get_stats()` counts `iframe_rows`, `resolvable_rows` and `direct_byte_rows`
apart so nobody can mistake one for another — this site has no stored byte
endpoint at all.

SUBTITLES: the site publishes none. Zero `.vtt`/`.srt` URLs appear in
`content.rendered` for any sampled post, and the embed hosts attach captions at
runtime (mxdrop's MDCore carries a `sublangs` language map and an `addSub`
call, not a track list). A row is only invented when a URL exists, so this site
contributes subtitle rows only if a probe actually finds one, and `raw_meta`
records the `subtitle_hint` we can prove instead.

TWO CLASSIFICATION DECISIONS AN AUDITOR WILL ASK ABOUT:

1. `year` comes from the site's own assertion about the WORK — the parenthetical
   in the title ("Haiwaan (2026) …", "Samarbhumi (Vanmurai Paguthi 2021) …") or
   a "2026 Movies"/"2024 Movies Hollywood" category — and `raw_meta.year_source`
   says which. It is never the post's publish date; `release_date` holds that
   and is labelled as such. This is the pagalmovies audit's defect, not repeated.
2. `is_18_plus` is keyword-based and errs toward flagging. The site has no adult
   category (all 275 names were read; none is adult), so the flag can only come
   from the title/taxonomy text. Explicit tokens flag outright; ambiguous ones
   ("sexy", "adult", "hot") flag only beside an explicit one or in a bare
   "18+"/"A"-certified title. A sibling site on this build list (moviehax) does
   publish "18+ … Adult Hindi Dubbed" titles, so the rule is real, not decorative.

Grouping: episodes are grouped under their show, exactly the way a merge tool
already expects (`posts` = work, `releases` = one print per site page, `sources`
= one row per player). The queue stays per-page, so re-scraping one episode
refreshes that episode's prints and touches no other episode's.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import html as html_mod
import http.cookiejar
import json
import re
import signal
import sqlite3
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import host_resolvers

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_URL = "https://www.moviesmela.com"
SITE = "moviesmela"
REST_POSTS = f"{BASE_URL}/wp-json/wp/v2/posts"
REST_CATEGORIES = f"{BASE_URL}/wp-json/wp/v2/categories"
DEFAULT_DB_PATH = Path("/home/ubuntu/radd-stream-data/moviesmela.db")
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)

PAGE_SIZE = 20
# Queue rows are committed as they are read, not at the end of the paging pass.
QUEUE_FLUSH_BATCH = 40
# per_page=20&_embed=1 answers 200 with content-length: 0 on this host; the
# taxonomy is resolved from /wp/v2/categories instead, so `_embed` is never sent.
LISTING_TIMEOUT = 60
MAX_PAGES = 1100          # X-WP-TotalPages was 1,045 on 2026-10-28
TAXONOMY_PAGE_CAP = 12    # 275 categories at per_page=100 is 3 pages; 12 is headroom
PROBE_SNIFF_BYTES = 120_000

QUEUED_SCRAPE_STATES = (0, 2)
PENDING_SELECT = (
    "SELECT loc, slug, raw_json FROM sitemap_cache"
    " WHERE scraped IN (%s) ORDER BY rowid ASC"
    % ", ".join(["?"] * len(QUEUED_SCRAPE_STATES))
)

LEGAL_MEDIA_TYPES = ("movie", "series", "complete_season")

# The honest answer for a link this importer cannot open: it is an iframe of
# someone else's player, and whether that player serves a byte today is unknown
# until a resolver says so.
DEFAULT_SOURCE_STATUS = "unverified"

# The two hosts `host_resolvers` can take from an embed URL to a byte endpoint.
# A row whose service is here is stored `playback_type='url'`, `is_temporary=1`
# with the embed URL as its identifier; every other host stays an iframe.
RESOLVABLE_SERVICES = frozenset({host_resolvers.SERVICE_MXDROP,
                                 host_resolvers.SERVICE_PKEMBED})

# Patched by the tests: no suite may sleep, and no suite may reach the network.
_sleep = time.sleep

STOP_REQUESTED = False


def _signal_handler(signum, frame):
    global STOP_REQUESTED
    STOP_REQUESTED = True
    print(f"[!] [{SITE}] {signum} received; draining in-flight pages…", flush=True)


def _install_signal_handlers() -> bool:
    """Returns False when there is no main thread to own the signals."""
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _signal_handler)
        except ValueError:
            return False
    return True


# ---------------------------------------------------------------------------
# Host rules
# ---------------------------------------------------------------------------

SITE_HOST_RE = re.compile(r"(?:^|\.)moviesmela\.[a-z]{2,}$", re.I)

# The player hosts this site actually embeds, observed live across 820 posts.
# Membership is label-anchored: a look-alike domain is not one of these players,
# and an ad network or link shortener must never become a row a client is shown.
EMBED_HOST_RE = re.compile(
    r"(?:^|\.)(?:mxdrop\.(?:to|top)|pkembed\.(?:site|online)|do7go\.com|ok\.ru"
    r"|vkcdn5\.[a-z]{2,}|dd133\.com|embedpk\.net|playmogo\.com|myvidplay\.com"
    r"|dsvplay\.com|filemoon\.[a-z]{2,})$",
    re.I,
)

# Download/shortlink bridges seen on sibling sites. They are named here so the
# importer can say "this is a gate page, not a file" instead of logging it as a
# download the catalog offers.
BRIDGE_HOST_RE = re.compile(
    r"(?:^|\.)(?:fastdlserver\.site|gdflix\.cfd|linksmod\.top|mobilejsr\.com"
    r"|linkvertise\.com)$",
    re.I,
)
# A gate can also be a path on an otherwise ordinary host ("…/download1.php"
# behind a Cloudflare Turnstile on a sibling site).
BRIDGE_PATH_RE = re.compile(r"/download1\.php(?:[?#]|$)", re.I)

MEDIA_EXT_RE = re.compile(r"\.(?:m3u8|mpd|mp4|webm|mkv)(?:[?#]|$)", re.I)
SUB_TRACK_RE = re.compile(r"\.(?:vtt|srt)(?:[?#]|$)", re.I)
TRACKER_HOST_RE = re.compile(
    r"(?:^|\.)(?:doubleclick\.net|googlesyndication\.com|googletagmanager\.com"
    r"|google-analytics\.com|taboola\.com|outbrain\.com|popads\.net"
    r"|bit\.ly|is\.gd|tinyurl\.com)$", re.I)
TEMPORARY_URL_RE = re.compile(r"(?:\?|&)(?:token|expires|auth_key|sign)=")

# ---------------------------------------------------------------------------
# Title grammar
# ---------------------------------------------------------------------------
# The site's titles are one SEO sentence:
#   <Show> ( <Year> [Ep 7-8 | Episode 51 | EP 12] ) <Lang> [Unofficial] [Dubbed]
#   <Full Movie | Season N [Complete] | Season N Episode 102 [13-JAN]>
#   Watch [Online] [Full Movie] [HD] [Print] [Quality] [DVD] Free Download
YEAR_RE = re.compile(r"\b((?:19|20)\d{2})\b")
PAREN_BLOCK_RE = re.compile(r"\(([^()]*)\)")
TITLE_YEAR_RE = re.compile(r"\b(19|20)(\d{2})\b")
EPISODE_RE = re.compile(
    r"\b(?:episode|ep\.?|e)\s*#?\s*(\d{1,4})(?:\s*[-–/]\s*(\d{1,4}))?\b", re.I)
# The site spells "Season" wrongly on some pages ("Seaosn 1 Complete"); the
# number is still its own assertion, so both spellings are read and the typo is
# recorded in raw_meta.season_source rather than silently normalised away.
SEASON_RE = re.compile(r"\b(season|seaosn)\s*(\d{1,3})\b", re.I)
COMPLETE_RE = re.compile(r"\b(?:season|seaosn)\s*\d{1,3}\s*complete\b|\bcomplete\b", re.I)
UNOFFICIAL_RE = re.compile(r"\bunofficial\b", re.I)
AIRDATE_BRACKET_RE = re.compile(r"\[(\d{1,2}(?:st|nd|rd|th)?[- ][A-Z]{3})\]")
PART_RE = re.compile(r"\bpart\s*(\d{1,2})\b", re.I)

# SEO packaging words that are never part of the work's name.
SEO_TAIL_RE = re.compile(
    r"""(?:\s|[-|»:,:])\s*(?:
        watch\s+(?:online\s+)?(?:full\s+movie\s+)?(?:online\s+)?
      | free\s+download
      | watch\s+full\s+movie
      | print\s+quality | print
      | dvdrip | dvd\s+rip | dvd
      | full\s+hd | hdrip | hd
      | watch\s+online
      | free\s+hd
      | download
    )\b.*$""",
    re.I | re.VERBOSE,
)
# The house quality vocabulary (import_pagalmovies.QUALITY_RE), then this site's
# own claim. "HD Print" is the site's wording for a clean rip; it is stored as
# quality="HD" with the exact token kept in raw_meta.quality_claim, so the column
# stays comparable with the other catalogs and nothing is thrown away.
QUALITY_RE = re.compile(r"\b(2160p|4k|1080p|720p|576p|480p|360p)\b", re.I)
QUALITY_BY_CLAIM = {"hdprint": "HD", "printquality": "HD", "hd": "HD", "dvd": "DVD",
                    "webdl": "web-dl", "web-dl": "web-dl", "hdtc": "hdtc", "cam": "cam"}
QUALITY_CLAIM_RE = re.compile(r"\b(hd\s*print|print\s*quality|hd|dvd|web-?dl|hdtc|cam)\b", re.I)
CODEC_RE = re.compile(r"\b(x264|x265|h\.?265|h\.?264|hevc|avc|prores)\b", re.I)

# Display-string brand scrub only. source_site / url / slug / service legitimately
# name the host and are never scrubbed.
BRAND_TOKEN_RE = re.compile(
    r"movies\s?mela|movies\s?flix(?:es)?|moviesmelacom|moviesmela\.com", re.I)

BRACKET_DATE_RE = re.compile(r"^\d{1,2}(?:st|nd|rd|th)?-[A-Z]{3}$", re.I)
# A slug ending in "-2024" carries the year the title forgot to state.
SLUG_YEAR_RE = re.compile(r"[-\s]((?:19|20)\d{2})\s*$")
NUMBERING_WORD_RE = re.compile(
    r"\b(?:episode|ep|season|part|complete|unofficial)\b", re.I)
# Any post text that advertises the site's own players is packaging, not a
# description of the work, however different its wording is from the title.
SEO_AD_RE = re.compile(
    r"\b(?:watch online|free download|dvd download|print quality|from player"
    r"|full show|web release)\b", re.I)
IFRAME_BLOCK_RE = re.compile(r"<iframe\b.*?</iframe>|<iframe\b[^>]*/?>", re.S | re.I)
HEADING_BLOCK_RE = re.compile(r"<h[1-6]\b[^>]*>.*?</h[1-6]>", re.S | re.I)

LANGUAGE_WORDS = (
    "hindi", "urdu", "english", "punjabi", "tamil", "telugu", "kannada",
    "malayalam", "bengali", "marathi", "gujarati", "oriya", "sinhala", "nepali",
)
LANGUAGE_TITLECASE = {
    "hindi": "Hindi", "urdu": "Urdu", "english": "English", "punjabi": "Punjabi",
    "tamil": "Tamil", "telugu": "Telugu", "kannada": "Kannada",
    "malayalam": "Malayalam", "bengali": "Bengali", "marathi": "Marathi",
    "gujarati": "Gujarati", "oriya": "Oriya", "sinhala": "Sinhala",
    "nepali": "Nepali",
}

# ---------------------------------------------------------------------------
# Taxonomy vocabulary (all 275 category names were read live on 2026-10-28)
# ---------------------------------------------------------------------------

INDUSTRY_BY_CATEGORY = {
    "Indian Movies": ("Bollywood", "India"),
    "Hollywood Movies": ("Hollywood", "USA"),
    "English Movies": ("Hollywood", "UK/USA"),
    "South Indian Dubbed Hindi": ("South India", "India"),
    "South indian": ("South India", "India"),
    "Watch Bollywood Movies Online": ("Bollywood", "India"),
    "Watch Full Punjabi Movies Online": ("Punjabi", "India"),
    "Old Bollywood Movies": ("Bollywood", "India"),
    "Hindi Dubbed Movies": ("Dubbed", "India"),
    "Urdu Dubbed Movies": ("Dubbed", "Pakistan"),
    "Animated Hindi Movies": ("Animation", "India"),
    "Animated English Movies": ("Animation", "USA"),
    "Punjabi Movies": ("Punjabi", "India"),
}
GENRE_BY_CATEGORY = {
    "action movies": "Action", "Action Movies": "Action",
    "Horror Movies": "Horror", "Romantic Movies": "Romance",
    "Thriller Movies": "Thriller", "crime movies": "Crime",
    "Funny Movies": "Comedy", "Funny": "Comedy", "Comedy": "Comedy",
    "Stage Drama": "Drama", "Suspense Movies": "Thriller",
    "Adventure Movies": "Adventure", "Documentary Movies": "Documentary",
    "Biographical Movies": "Biography", "Sports Movies": "Sport",
    "Sci-Fi Movies": "Sci-Fi", "Mystery Movies": "Mystery",
    "Family Movies": "Family", "War Movies": "War",
    "Historical Movies": "History", "Musical Movies": "Music",
    "Wrestling Videos": "Wrestling",
}
# Non-work categories: keepers for raw_meta, never metadata columns.
NOISE_CATEGORIES = frozenset({
    "Articles", "upcoming movies", "Most Viewed movies", "featured",
    "Slot Oyna", "Comedy nights with kapil", "India's Got Talent",
})
SERIES_PARENT_NAMES = ("Shows / Series", "Seasons / WebSeries")
ACTOR_CATEGORY_RE = re.compile(r"\bmovies?\s+(?:list|lisy)\b", re.I)
YEAR_CATEGORY_RE = re.compile(r"^\s*(\d{4})\s+Movies(?:\s+Hollywood)?\s*$", re.I)
SEASON_CATEGORY_RE = re.compile(r"\b(?:seaosn|season)\s*(\d{1,3})\b", re.I)
CAST_SUFFIX_RE = re.compile(r"\s*(?:full\s+)?movies?\s+(?:list|lisy)\s*$|\s+movies?\s*$", re.I)

ADULT_RE = re.compile(
    # `xxx` left this tier on 2026-10-29: 62 rows were hidden by it alone and this catalog
    # holds the *xXx* films, so one hit is a suggestion, not a hide. `adult` stays — 10/12
    # sampled live titles carrying it are real product ("… Adult Short Film"), and the two
    # *Shin-chan: The Adult Empire Strikes Back* rows it also catches are the documented
    # cost. See `fast_fetch.ADULT_TITLE_PATTERNS` for the law and the sampling method.
    r"\b(?:porn(?:ographic)?|erotic|adult(?:\s+only)?|blue\s+film"
    r"|aunty\s+sex|bua\s?wa|sex\s+scene|nude|naked|mms|hardcore|blowjob"
    r"|onlyfans|only\s+fans)\b"
    # A trailing \b after "18+" can never match (the next character is a space,
    # and neither side of it is a word character), so this token stands alone.
    r"|\b18\+", re.I)
AMBIGUOUS_ADULT_RE = re.compile(
    r"\b(?:sexy|lust|sensual|bed\s*scene|hot\s+short\s+film|intimate)\b", re.I)
AGE_CERT_RE = re.compile(r"\bA\s*certified\b|\b\bA\b\s*/\s*18\b", re.I)

ADULT_PROSE_RE = re.compile(
    r"\b(?:adult film|18\+ (?:movie|film|web series)|erotic)\b", re.I)


# ---------------------------------------------------------------------------
# Fetch seams
# ---------------------------------------------------------------------------


def _build_ssl_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    return context


class _StopRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _build_openers(context: ssl.SSLContext, cookie: http.cookiejar.CookieJar):
    """Two openers: one that follows redirects, one that reports them."""
    following = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=context),
        urllib.request.HTTPCookieProcessor(cookie))
    stopping = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=context),
        urllib.request.HTTPCookieProcessor(cookie),
        _StopRedirect(),
    )
    return following, stopping


_SSL_CONTEXT = _build_ssl_context()
_COOKIE_JAR = http.cookiejar.CookieJar()
_OPENER, _NO_REDIRECT_OPENER = _build_openers(_SSL_CONTEXT, _COOKIE_JAR)


def _open(request, follow: bool = True, timeout: int = 30):
    """
    The single network primitive.

    Every test patches this and nothing else, so both seam bodies — the retry
    loop and the redirect-reporting path — really execute.
    """
    opener = _OPENER if follow else _NO_REDIRECT_OPENER
    return opener.open(request, timeout=timeout)


def http_get(url: str, timeout: int = 30, retries: int = 3):
    """GET with a bounded retry on transport failure. Returns (status, body)."""
    last_status, last_body = 0, ""
    for attempt in range(max(1, retries)):
        if STOP_REQUESTED:
            return last_status, last_body
        request = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
        try:
            with _open(request, follow=True, timeout=timeout) as response:
                body = response.read().decode("utf-8", "replace")
                return getattr(response, "status", 200) or 200, body
        except urllib.error.HTTPError as exc:
            return exc.code, ""
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_status, last_body = 0, f"{type(exc).__name__}: {exc}"
        except Exception as exc:
            return 0, f"{type(exc).__name__}: {exc}"
        if attempt + 1 < max(1, retries):
            _sleep(1.5 * (attempt + 1))
    return last_status, last_body


def http_get_once(url: str, referer: str | None = None, timeout: int = 25):
    """
    One GET that does not follow redirects — the probe's view of a player URL.

    Returns (status, body, location). A 3xx is a fact about the host (mxdrop.to
    answers 302 to mxdrop.top for every post), not a transport error.
    """
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,*/*"}
    if referer:
        headers["Referer"] = referer
    request = urllib.request.Request(url, headers=headers)
    try:
        with _open(request, follow=False, timeout=timeout) as response:
            status = getattr(response, "status", 200) or 200
            body = response.read(PROBE_SNIFF_BYTES).decode("utf-8", "replace")
            return status, body, ""
    except urllib.error.HTTPError as exc:
        code = exc.code
        if code in (301, 302, 303, 307, 308):
            return code, "", exc.headers.get("Location") or ""
        try:
            return code, exc.read(PROBE_SNIFF_BYTES).decode("utf-8", "replace"), ""
        except Exception:
            return code, "", ""
    except Exception as exc:
        return 0, "", f"{type(exc).__name__}: {exc}"


def get_json(url: str, timeout: int = LISTING_TIMEOUT):
    """
    (status, payload) where payload is None unless the body parsed as JSON.

    `200 + content-length: 0` is a real answer on this host (measured on
    per_page=20&_embed=1), so an empty body is reported as status 200 with no
    payload rather than raising out of json.loads.
    """
    status, body = http_get(url, timeout=timeout)
    if not body or not body.strip():
        return status, None
    try:
        return status, json.loads(body)
    except json.JSONDecodeError:
        return status, None


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------


def _unescape(text: str | None) -> str:
    return html_mod.unescape(text or "")


def _clean_text(text: str | None) -> str:
    return re.sub(r"\s+", " ", _unescape(text)).strip()


def scrub_brand(text: str | None) -> str:
    """Removes this site's own brand from a display string, never a host field."""
    cleaned = BRAND_TOKEN_RE.sub(" ", _clean_text(text))
    return re.sub(r"\s+", " ", cleaned).strip(" -|:,")


def _host_of(url: str) -> str:
    return (urllib.parse.urlsplit(url or "").netloc or "").lower()


def _is_site_url(url: str) -> bool:
    return bool(SITE_HOST_RE.search(_host_of(url)))


def _is_embed_host(url: str) -> bool:
    return bool(EMBED_HOST_RE.search(_host_of(url)))


def playability_note(players: list[dict]) -> str:
    """
    What this page's rows can honestly promise a client, in one sentence.

    Written per page rather than as a constant, because a page mixing an mxdrop
    row with filemoon iframes is a different claim from a page of iframes only,
    and the note is what stops a future reader from counting rows as watchable.
    """
    services = sorted({row["service"] for row in players})
    resolvable = sorted({row["service"] for row in players
                         if row["playback_type"] != "iframe"})
    if not resolvable:
        return ("every row this page contributes is a third-party iframe; none "
                "is a byte endpoint, and the Android client has no WebView "
                f"escape hatch ({', '.join(services) or 'no players'})")
    return (f"{', '.join(resolvable)} resolves to a signed mp4 on demand "
            "(host_resolvers); the other rows "
            f"({', '.join(s for s in services if s not in resolvable) or 'none'}) "
            "are iframes the client cannot play; no row on this page is a "
            "stored byte endpoint, and a signed URL is never persisted")


def _player_kind(url: str) -> tuple[str, str, bool]:
    """
    (service, playback_type, resolvable) for one embed URL.

    Two hosts in this catalog let a pure-stdlib chain reach a byte endpoint,
    both verified live on 2026-10-28: mxdrop (packed MDCore config in base 10,
    `MDCore.wurl`) and pkembed (the same packer in base 36, four arguments and
    no trailing `0,{}`, whose payload publishes `<source>` renditions on
    `plusN.vkpluscdn.site` or `stoplus.vkcdn5.com`). Both are probed the same
    way — `Range: bytes=0-511`, no Referer — and both answer `206 video/mp4`, so
    their rows are resolvable URLs, which is what `viewer.py` maps to kind
    `resolve` and what the JIT resolver can serve on demand.

    Every other player host stays `iframe`: the Android client has no WebView,
    so an iframe is catalog evidence about a third-party page and nothing a
    client can play. Storing one as a stream would be a false promise. Two of
    those hosts — `filemoon` and `movieshub.rpmplay.xyz` — were examined for a
    stdlib path on 2026-10-28; the measurements that settled the NEEDS-JS
    verdict are recorded in `host_resolvers` under "HOSTS DELIBERATELY NOT
    IMPLEMENTED". Both are single-page apps whose byte endpoint only a browser
    reaches, and rpmplay's additionally requires a capacity-token handshake
    gated on browser-integrity signals, which is not something to imitate.

    The row's `source_url` is always the embed URL. mxdrop signs for about six
    hours and pkembed for twelve (`s` + `e`), so a stored copy of either mp4 URL
    is a 403 by morning; the embed URL is the durable identifier.
    """
    if host_resolvers.is_mxdrop_embed(url):
        return host_resolvers.SERVICE_MXDROP, "url", True
    if host_resolvers.is_pkembed_embed(url):
        return host_resolvers.SERVICE_PKEMBED, "url", True
    return _host_of(url), "iframe", False


def _normalize_http_url(url: str, base: str = BASE_URL) -> str:
    """protocol-relative (`//ok.ru/…`) and schemeless URLs -> absolute http(s)."""
    raw = (url or "").strip()
    if not raw:
        return ""
    if raw.startswith("//"):
        return "https:" + raw
    if not re.match(r"^https?://", raw, re.I):
        return urllib.parse.urljoin(base, raw)
    return raw


def _resource_id(url: str) -> str:
    """
    The hoster's own id for this print: /videoembed/<id>, /e/<token>,
    embed-<token>.html. It is what a resolver would need, so it is kept.
    """
    parts = urllib.request.url2pathname(urllib.parse.urlsplit(url or "").path)
    segments = [s for s in parts.split("/") if s]
    if not segments:
        return ""
    if segments[0].lower() == "videoembed" and len(segments) > 1:
        return segments[1]
    last = segments[-1]
    if last.lower().endswith(".html") and last.lower().startswith("embed-"):
        return last[:-5]
    return re.sub(r"\.(?:html?|php)$", "", last)


def _is_temporary(url: str) -> int:
    return 1 if TEMPORARY_URL_RE.search(url or "") else 0


def _slugify(text: str | None) -> str:
    words = re.sub(r"[^\w\s-]", " ", _unescape(text or "").lower(), flags=re.U)
    words = re.sub(r"[\s_-]+", "-", words, flags=re.U).strip("-")
    return words


def slug_name(slug: str | None) -> tuple[str, int | None]:
    """
    The slug as a display name, plus the year it carries at the end.

    Used only when the title is pure SEO packaging and states no name. The
    trailing 4-digit group is the work's year rather than part of its name; the
    title's own year still wins, so this never overrides a stated one.
    """
    text = _clean_text((slug or "").replace("-", " "))
    match = SLUG_YEAR_RE.search(text)
    if not match:
        return text, None
    return _clean_text(text[:match.start()]), int(match.group(1))


# ---------------------------------------------------------------------------
# Page parsing — pure, no I/O
# ---------------------------------------------------------------------------

IFRAME_SRC_RE = re.compile(r"""<iframe\b[^>]*?\bsrc\s*=\s*["']?([^"'\s>]+)""", re.I)
PLAYER_HEADING_RE = re.compile(r"From\s+Player\s+(\d+)\s+Below", re.I)
ANY_TAG_RE = re.compile(r"<[^>]+>", re.I)


def parse_players(content: str | None) -> list[dict]:
    """
    Every iframe the post publishes, in the site's own player order.

    The `<h2>Watch … From Player N Below</h2>` heading names the slot; when a
    post omits it, the ordinal falls back to position, so a label is never a
    guess about which server the site meant.
    """
    body = content or ""
    headings = [int(m.group(1)) for m in PLAYER_HEADING_RE.finditer(body)]
    rows = []
    for index, match in enumerate(IFRAME_SRC_RE.finditer(body), start=1):
        url = _normalize_http_url(match.group(1))
        label = (f"Player {headings[index - 1]}"
                 if index <= len(headings) else f"Player {index}")
        service, playback_type, resolvable = _player_kind(url)
        rows.append({
            "source_url": url,
            "service": service,
            "resource_id": _resource_id(url),
            "source_name": label,
            "playback_type": playback_type,
            "status": DEFAULT_SOURCE_STATUS,
            # For a resolvable row the flag describes what the row resolves to
            # (a signature that expires in hours), not the embed URL itself.
            "is_temporary": True if resolvable else _is_temporary(url),
            "allowed": _is_embed_host(url),
        })
    return rows


def split_players(content: str | None) -> tuple[list[dict], list[dict]]:
    """(accepted players, refused hosts) — a refused host is reported, never dropped."""
    accepted, refused = [], []
    for row in parse_players(content):
        (accepted if row.pop("allowed") else refused).append(row)
    return accepted, refused


def find_download_links(content: str | None) -> list[dict]:
    """
    External `<a>` targets. None exist on this site (820 posts sampled); a bridge
    page (shortener/interstitial) is labelled as one rather than as a download.
    """
    rows = []
    for match in re.finditer(r'<a[^>]+href=["\']([^"\']+)["\']', content or "", re.I):
        url = _normalize_http_url(match.group(1))
        host = _host_of(url)
        if not host or _is_site_url(url) or TRACKER_HOST_RE.search(host):
            continue
        rows.append({
            "source_url": url, "service": host, "resource_id": _resource_id(url),
            "source_name": "Download", "playback_type": "download",
            "status": ("blocked" if BRIDGE_HOST_RE.search(host)
                       or BRIDGE_PATH_RE.search(url) else "unverified"),
            "is_temporary": _is_temporary(url),
        })
    return rows


def parse_title(title: str | None) -> dict:
    """
    The site's one-sentence title -> the work's name plus what the sentence says
    about it. Every field records the text it came from, so nothing here is
    inferred from a vibe.
    """
    raw = _unescape(title or "").strip()
    out = {
        "raw_title": raw, "base_title": "", "year": None, "year_source": None,
        "episode": None, "episode_end": None, "season": None,
        "complete_season": False, "languages": [], "quality": None,
        "resolution": None, "unofficial": bool(UNOFFICIAL_RE.search(raw)),
        "air_date_tag": None, "original_title": None, "quality_claim": None,
        "season_source": None,
    }
    if not raw:
        return out

    parens = PAREN_BLOCK_RE.findall(raw)
    for block in parens:
        digits = TITLE_YEAR_RE.findall(block)
        if digits:
            out["year"] = int("".join(digits[-1]))
            out["year_source"] = "title-paren"
        tag = AIRDATE_BRACKET_RE.search(block)
        if tag:
            out["air_date_tag"] = _clean_text(tag.group(1))
        rest = _clean_text(TITLE_YEAR_RE.sub(" ", block))
        # "(Vanmurai Paguthi 2021)" names the original work; "(2026 Episode 51)"
        # does not, so a paren holding a numbering token is not an original title.
        if rest and not NUMBERING_WORD_RE.search(rest) and not BRACKET_DATE_RE.match(rest):
            out["original_title"] = rest
    if not parens:
        tag = AIRDATE_BRACKET_RE.search(raw)
        if tag:
            out["air_date_tag"] = _clean_text(tag.group(1))

    episode = EPISODE_RE.search(raw)
    if episode:
        out["episode"] = int(episode.group(1))
        if episode.group(2):
            out["episode_end"] = int(episode.group(2))
    season = SEASON_RE.search(raw)
    if season:
        out["season"] = int(season.group(2))
        out["season_source"] = ("title-token-typo" if season.group(1).lower() == "seaosn"
                                else "title-token")
    if not out["air_date_tag"]:
        tag = AIRDATE_BRACKET_RE.search(raw)
        if tag:
            out["air_date_tag"] = _clean_text(tag.group(1))
    if not out["year"]:
        year = YEAR_RE.search(raw)
        if year:
            out["year"] = int(year.group(1))
            out["year_source"] = "title-token"

    lowered = raw.lower()
    for word in LANGUAGE_WORDS:
        if re.search(rf"\b{word}\b", lowered):
            out["languages"].append(LANGUAGE_TITLECASE[word])
    if COMPLETE_RE.search(raw):
        out["complete_season"] = True

    claim = QUALITY_CLAIM_RE.search(raw)
    if claim:
        out["quality_claim"] = _clean_text(claim.group(0))
        out["quality"] = QUALITY_BY_CLAIM.get(claim.group(0).lower().replace(" ", ""),
                                             _clean_text(claim.group(0)).upper())
    resolution = QUALITY_RE.search(raw)
    if resolution:
        out["resolution"] = resolution.group(1).lower()
        out["quality"] = resolution.group(1).lower()

    stripped = raw
    if parens:
        stripped = PAREN_BLOCK_RE.sub(" ", stripped, count=len(parens))
    stripped = re.sub(r"\[[^\]]*\]", " ", stripped)
    stripped = SEO_TAIL_RE.sub(" ", stripped)
    # Numbering groups are removed before the word list: "Season 14" must leave
    # as a unit, or the bare 14 survives into the show's name and every season of
    # Bigg Boss becomes a different canonical_key.
    stripped = re.sub(
        r"\b(?:final\s+)?(?:season|seaosn|ep(?:isode)?\.?)\s*#?\d+(?:\s*[-–/]\s*\d+)?\b",
        " ", stripped, flags=re.I)
    stripped = re.sub(
        r"\b(?:episode|season|complete|full\s+movie|dubbed|unofficial"
        r"|watch(?:\s+online)?|free\s+download|print(?:\s+quality)?|dvd|hd|4k"
        r"|1080p|720p|480p|hdtc|web-?dl|hindi|urdu|english|punjabi|tamil|telugu"
        r"|kannada|malayalam|bengali|marathi|seaosn)\b", " ",
        stripped, flags=re.I)
    if out["year"]:
        # Only the year this title itself asserted is packaging; a number that
        # belongs to the work ("3 Idiots", "1% chance") is part of its name.
        stripped = re.sub(rf"\b{out['year']}\b", " ", stripped)
    out["base_title"] = scrub_brand(re.sub(r"\s+", " ", stripped)).strip(" -|:,")
    return out


def extract_synopsis(content: str | None, raw_title: str, base_title: str) -> str | None:
    """
    Prose the site wrote about the work, or None.

    Every sampled post closes with the SEO sentence — the title restated and
    joined to a "Watch Online DVD Download" clause — and that is not a synopsis.
    A remainder whose opening names the work again is that restatement, so it is
    dropped; genuinely different prose is kept.

    Markup goes before any of that is judged: a post may wrap its embed in bare
    `<a href>` tags, and a display string that still carried them would show the
    Android client its own angle brackets.
    """
    text = _clean_text(ANY_TAG_RE.sub(" ", HEADING_BLOCK_RE.sub(
        " ", IFRAME_BLOCK_RE.sub(" ", content or ""))))
    if not text or len(text) < 20:
        return None
    if SEO_AD_RE.search(text):
        return None
    slug_text = _slugify(text)
    slug_work = _slugify(base_title)
    if slug_work and slug_text.startswith(slug_work[:max(8, len(slug_work) // 2)]):
        return None
    return text


def taxonomy_fields(category_names: list[str]) -> dict:
    """
    Category names -> the columns they legitimately answer for.

    The site's taxonomy is inconsistent about `parent` (Bigg Boss Season 20 is
    parent=0 while Season 19 is parent=2536), so a season category is recognised
    by its NAME, never by its parent.
    """
    fields = {
        "genres": [], "cast": [], "industry": None, "country": None,
        "audio_languages": [], "season": None, "year": None, "show_category": None,
        "noise": [], "unmapped": [],
    }
    for name in category_names:
        clean = _clean_text(name)
        if not clean:
            continue
        year_cat = YEAR_CATEGORY_RE.match(clean)
        if year_cat:
            # A "2024 Movies" category asserts the release year; putting it in
            # genres as well would double the same claim into two columns.
            fields["year"] = fields["year"] or int(year_cat.group(1))
            continue
        season_cat = SEASON_CATEGORY_RE.search(clean)
        if season_cat and not ACTOR_CATEGORY_RE.search(clean):
            fields["season"] = fields["season"] or int(season_cat.group(1))
            fields["show_category"] = clean
            fields["genres"].append("Web Series")
            continue
        if clean in SERIES_PARENT_NAMES:
            fields["genres"].append("Web Series")
            continue
        if clean in INDUSTRY_BY_CATEGORY:
            industry, country = INDUSTRY_BY_CATEGORY[clean]
            fields["industry"] = fields["industry"] or industry
            fields["country"] = fields["country"] or country
            if clean == "Hindi Dubbed Movies":
                fields["audio_languages"].append("Hindi")
            elif clean == "Urdu Dubbed Movies":
                fields["audio_languages"].append("Urdu")
            elif clean == "English Movies":
                fields["audio_languages"].append("English")
            elif clean == "Watch Full Punjabi Movies Online":
                fields["audio_languages"].append("Punjabi")
            continue
        if clean in GENRE_BY_CATEGORY:
            fields["genres"].append(GENRE_BY_CATEGORY[clean])
            continue
        if clean in NOISE_CATEGORIES:
            fields["noise"].append(clean)
            continue
        if ACTOR_CATEGORY_RE.search(clean):
            person = CAST_SUFFIX_RE.sub("", clean).strip()
            if person.islower():
                # The site's own actor categories are inconsistently cased
                # ("sanjay dutt movies list"); capitalising a person name is
                # display hygiene, not a claim about who the person is.
                person = " ".join(w.capitalize() for w in person.split())
            if person:
                fields["cast"].append(person)
            continue
        fields["unmapped"].append(clean)
    fields["genres"] = list(dict.fromkeys(fields["genres"]))
    fields["cast"] = list(dict.fromkeys(fields["cast"]))
    fields["audio_languages"] = list(dict.fromkeys(fields["audio_languages"]))
    return fields


def looks_adult(*labels: str, prose: tuple[str, ...] = ()) -> int:
    """
    Keyword rule, erring toward flagging (AGENTS.md: stored, never displayed).
    An ambiguous token counts only beside an explicit one or an A certification.
    """
    text = " ".join(x for x in labels if x)
    explicit = bool(ADULT_RE.search(text)) or bool(AGE_CERT_RE.search(text))
    if explicit:
        return 1
    if AMBIGUOUS_ADULT_RE.search(text) and (
            ADULT_PROSE_RE.search(" ".join(prose))):
        return 1
    return 0


def media_type_for(parsed: dict, has_show_category: bool) -> str:
    """movie | series | complete_season, from what the title and taxonomy assert."""
    if parsed["episode"] is not None:
        return "series"
    if parsed["complete_season"] or parsed["season"] is not None or has_show_category:
        return "complete_season"
    return "movie"


def release_label(parsed: dict, media_type: str) -> str:
    if parsed["episode"] is None:
        if media_type == "complete_season":
            season = parsed["season"]
            return (f"Season {season} Complete" if season else "Season Complete")
        return "Watch Online"
    number = parsed["episode"]
    if parsed["episode_end"] and parsed["episode_end"] != number:
        return f"Episodes {number}-{parsed['episode_end']}"
    return f"Episode {number}"


def poster_from_post(wp_post: dict) -> str:
    """
    The featured image, read from Yoast's og_image.

    `_embed` is unavailable at this page size, and /wp/v2/media/<id> would cost
    one request per post; Yoast already publishes the full-size upload URL
    (verified: Haiwaan's `…/2026/10/Haiwaan-2026-Hindi.jpg`, not a thumbnail).
    """
    yoast = wp_post.get("yoast_head_json") or {}
    images = yoast.get("og_image") or []
    if isinstance(images, list):
        for image in images:
            url = _normalize_http_url((image or {}).get("url") or "")
            if url:
                return url
    return ""


def build_post(wp_post: dict, categories: dict[int, str] | None = None) -> dict | None:
    """
    One REST post -> the staging record for its page.

    Returns None when the entry is not a catalog page (no slug, no players), so a
    stray "Articles" post cannot become a work row.
    """
    slug = wp_post.get("slug") or ""
    link = _normalize_http_url(wp_post.get("link") or "")
    if not slug or not link or not _is_site_url(link):
        return None
    content = (wp_post.get("content") or {}).get("rendered") or ""
    players, refused = split_players(content)
    downloads = find_download_links(content)
    if not players and not downloads:
        return None

    names = [(categories or {}).get(int(cid), f"category:{cid}")
             for cid in (wp_post.get("categories") or [])]
    tax = taxonomy_fields(names)
    parsed = parse_title(wp_post.get("title", {}).get("rendered") if isinstance(
        wp_post.get("title"), dict) else wp_post.get("title"))
    show = parsed["base_title"]
    slug_year = None
    if not show:
        show, slug_year = slug_name(slug)
    if not show:
        return None

    year = parsed["year"] or tax["year"] or slug_year
    if parsed["year"]:
        year_source = parsed["year_source"]
    elif tax["year"]:
        year_source = "year-category"
    elif slug_year:
        year_source = "slug-trailing-year"
    else:
        year_source = None
    season = parsed["season"] if parsed["season"] is not None else tax["season"]
    media_type = media_type_for({**parsed, "season": season}, bool(tax["show_category"]))

    key = _slugify(show)
    if not key:
        # A display name made only of punctuation slugs to nothing; declining it
        # here, before the year is appended, is what stops every such post from
        # colliding on a manufactured key like "-2026".
        return None
    if media_type == "movie" and year:
        key = f"{key}-{year}"

    audio = list(dict.fromkeys(tax["audio_languages"] + parsed["languages"]))
    synopsis = extract_synopsis(content, parsed["raw_title"], show)

    release = {
        "label": release_label({**parsed, "season": season}, media_type),
        "quality": parsed["quality"],
        "resolution": parsed["resolution"],
        "season_number": season,
        "episode_number": parsed["episode"],
        "audio_languages": ", ".join(audio) if audio else None,
        "bridge_url": None,
        "origin_url": link,
        "sources": players + downloads,
    }
    raw_meta = {
        "post_id": wp_post.get("id"),
        "page": {
            "url": link, "slug": slug, "title": parsed["raw_title"],
            "date": wp_post.get("date"), "modified": wp_post.get("modified"),
            "excerpt": _clean_text((wp_post.get("excerpt") or {}).get("rendered")
                                   if isinstance(wp_post.get("excerpt"), dict) else ""),
        },
        "categories": names,
        "tag_ids": list(wp_post.get("tags") or []),
        "unmapped_categories": tax["unmapped"],
        "noise_categories": tax["noise"],
        "show_category": tax["show_category"],
        "year_source": year_source,
        "quality_claim": parsed["quality_claim"],
        "season_source": parsed["season_source"],
        "original_title": parsed["original_title"],
        "unofficial_dub": parsed["unofficial"],
        "air_date_tag": parsed["air_date_tag"],
        "episode_range": ([parsed["episode"], parsed["episode_end"]]
                          if parsed["episode_end"] else None),
        "media_type": media_type,
        "release_label": release["label"],
        "players": [row["source_url"] for row in players],
        "refused_hosts": sorted({row["service"] for row in refused}),
        "download_links": [row["source_url"] for row in downloads],
        "subtitle_hint": None,
        "subtitle_note": ("the site publishes no subtitle track URLs; the embed "
                          "hosts attach captions at runtime (mxdrop MDCore.sublangs)"),
        "poster_source": "yoast:og_image",
        "playability_note": playability_note(players),
    }
    return {
        "canonical_key": key,
        "title": show,
        "clean_title": show,
        "year": year,
        "media_type": media_type,
        "poster_url": poster_from_post(wp_post) or None,
        "synopsis": synopsis,
        "genres": ", ".join(tax["genres"]) if tax["genres"] else None,
        "director": None,
        "cast_names": ", ".join(tax["cast"]) if tax["cast"] else None,
        "duration": None,
        "release_date": wp_post.get("date"),
        "languages": ", ".join(audio) if audio else None,
        "industry": tax["industry"],
        "country": tax["country"],
        "seasons": str(season) if season is not None else None,
        "url": link,
        "slug": slug,
        "is_18_plus": looks_adult(parsed["raw_title"], *names,
                                  prose=(synopsis or "",)),
        "is_animated": 1 if tax["industry"] == "Animation" else 0,
        "releases": [release],
        "raw_meta": raw_meta,
        "lastmod": wp_post.get("modified") or "",
        "page_url": link,
    }


def sources_for(release: dict) -> list[dict]:
    return list(release.get("sources") or [])


def classify(post: dict) -> dict:
    """Country/industry, re-derived from stored columns (kept for the house API)."""
    country = post.get("country")
    industry = post.get("industry")
    if not industry and country:
        industry = {"India": "Bollywood", "Pakistan": "Lollywood"}.get(country)
    return {"industry": industry, "country": country}


# ---------------------------------------------------------------------------
# Resolution: what a probe can honestly say about an iframe
# ---------------------------------------------------------------------------

JS_GATE_RE = re.compile(r"\b(login|log\s*in|sign\s*in|captcha|turnstile"
                        r"|verify you are human|just a moment|access denied)\b", re.I)
PLAYER_HINT_RE = re.compile(r"(?:jwplayer|videojs|video\.js|hls\.js|plyr"
                            r"|flowplayer|clappr|vidstack|mdcore|fluidplayer)", re.I)


def verdict_from_probe(status: int, body: str, location: str, error: str = "") -> dict:
    """
    A verdict about the *link answering*, never about ExoPlayer playability.

    200 + a player marker -> `active`: the hoster's page loaded and looks like a
    player. 403/401/429 -> `blocked`; 404/410 -> `dead`; 3xx -> `redirect` with
    the target stored; a 200 that is a login/captcha page -> `js_required`; a
    transport failure -> `unknown`. Subtitle/media URLs found in the body are
    returned for extra rows, because that is the only place a real track URL
    could ever come from on this site.
    """
    verdict = {"status": DEFAULT_SOURCE_STATUS, "location": "", "error": error,
               "media_urls": [], "subtitle_urls": []}
    if status == 0:
        verdict["status"] = "unknown"
        return verdict
    if status in (301, 302, 303, 307, 308):
        verdict["status"] = "redirect"
        verdict["location"] = location or ""
        return verdict
    if status in (401, 403, 429):
        verdict["status"] = "blocked"
        if JS_GATE_RE.search(body or ""):
            verdict["status"] = "js_required"
        return verdict
    if status in (404, 410, 451):
        verdict["status"] = "dead"
        return verdict
    if 500 <= status <= 599:
        verdict["status"] = "error"
        return verdict
    if status == 204:
        verdict["status"] = "blocked"
        return verdict
    if status != 200:
        verdict["status"] = "error"
        return verdict
    text = body or ""
    verdict["media_urls"] = [u for u in _extract_urls(text) if MEDIA_EXT_RE.search(u)]
    verdict["subtitle_urls"] = [u for u in _extract_urls(text) if SUB_TRACK_RE.search(u)]
    if JS_GATE_RE.search(text) and not PLAYER_HINT_RE.search(text):
        verdict["status"] = "js_required"
    elif PLAYER_HINT_RE.search(text) or verdict["media_urls"]:
        verdict["status"] = "active"
    else:
        verdict["status"] = "unknown"
    return verdict


def _extract_urls(text: str) -> list[str]:
    found = []
    for match in re.finditer(r"""(?:https?:)?//[^"'\s<>\\]+""", text):
        url = _normalize_http_url(match.group(0))
        host = _host_of(url)
        if not host or TRACKER_HOST_RE.search(host):
            continue
        if url not in found:
            found.append(url)
    return found


def probe_source(url: str, referer: str | None = None) -> dict:
    status, body, location = http_get_once(url, referer=referer)
    error = location if status == 0 else ""
    return verdict_from_probe(status, body, location, error=error)


def resolve_links(post: dict, probe: bool = False, deep: bool = False,
                  referer: str = BASE_URL + "/") -> dict:
    """
    Optionally probe what each row's host actually answers.

    Probe is opt-in because it is one to three requests per player per page
    (4 players x 20,888 pages is not a polite crawl) and because the default
    crawl is a local transform of what sync already downloaded — no socket at
    all. A resolvable row (mxdrop or pkembed) is unpacked and Range-probed
    against `host_resolvers`, which never sends this site's Referer (mxdrop's
    CDN 403s on it); the signed mp4 it returns is reported, not stored. An
    iframe row's answer does not change what the row *is*.
    """
    checked = int(time.time())
    evidence = []
    for release in post.get("releases") or []:
        for source in sources_for(release):
            service = source.get("service")
            if service in RESOLVABLE_SERVICES:
                if not probe:
                    source["status"] = DEFAULT_SOURCE_STATUS
                    continue
                # Looked up per service: pkembed's payload differs in packer
                # radix, in publishing `<source>` renditions rather than
                # MDCore.wurl, and in counting its expiry from `s` for `e`
                # seconds rather than reading `e` as an epoch.
                unwrap = (host_resolvers.unwrap_pkembed
                          if service == host_resolvers.SERVICE_PKEMBED
                          else host_resolvers.unwrap_mxdrop)
                verdict = unwrap(source["source_url"])
                source["status"] = verdict["status"]
                source["last_checked"] = checked
                item = {
                    "service": service, "embed_url": verdict["embed_url"],
                    "poster_url": verdict["poster_url"],
                    "quality": verdict.get("quality", ""),
                    "renditions": [track["label"] for track in verdict.get("sources") or []
                                   if track.get("label")],
                    "expires_in": verdict["expires_in"],
                    "signed_params": verdict["signed_params"],
                    "subtitles": verdict["subtitles"], "status": verdict["status"],
                    "http_status": verdict.get("http_status"),
                    "size_bytes": verdict.get("size_bytes"),
                    "content_type": verdict.get("content_type"),
                    "notes": verdict["notes"],
                }
                if verdict.get("vfile"):
                    # mxdrop-only fields: the host's own file hash and server
                    # name. Recorded when the host published them, not invented.
                    item["vfile"] = verdict["vfile"]
                    item["vserver"] = verdict["vserver"]
                evidence.append(item)
                continue
            if not probe:
                source.setdefault("status", DEFAULT_SOURCE_STATUS)
                continue
            referer_url = None if _host_of(source["source_url"]).endswith("ok.ru") else referer
            verdict = probe_source(source["source_url"], referer=referer_url)
            source["status"] = verdict["status"]
            source["last_checked"] = checked
            if verdict["error"]:
                source["probe_error"] = verdict["error"]
            if deep and verdict["location"]:
                source["final_url"] = _normalize_http_url(
                    verdict["location"], base=source["source_url"])
            if verdict["media_urls"] or verdict["subtitle_urls"]:
                raw = post.setdefault("raw_meta", {})
                if isinstance(raw, str):
                    raw = {}
                raw["probed_media_urls"] = verdict["media_urls"]
                raw["probed_subtitle_urls"] = verdict["subtitle_urls"]
                if verdict["subtitle_urls"]:
                    post.setdefault("discovered_subtitles", []).extend(
                        verdict["subtitle_urls"])
    if evidence:
        raw = post.setdefault("raw_meta", {})
        if not isinstance(raw, dict):
            raw = {}
        for service in sorted({item["service"] for item in evidence}):
            raw[service] = [item for item in evidence if item["service"] == service]
        subs = sorted({track["language"] for item in evidence
                       for track in item["subtitles"]})
        published_by = sorted({item["service"] for item in evidence if item["subtitles"]})
        raw["subtitle_note"] = (
            f"{', '.join(published_by)} published subtitle tracks on this page: "
            + ", ".join(subs)
            if subs else raw.get("subtitle_note"))
    post["resolved"] = {"probe": bool(probe), "deep": bool(deep)}
    return post


# ---------------------------------------------------------------------------
# Staging database
# ---------------------------------------------------------------------------

POST_COLUMNS = (
    "canonical_key", "title", "clean_title", "year", "media_type", "poster_url",
    "backdrop_url", "backdrop_urls", "imdb_id", "tmdb_id", "imdb_rating", "synopsis",
    "genres", "director", "cast_names", "duration", "release_date", "languages",
    "industry", "country", "seasons", "url", "slug", "is_18_plus", "is_animated",
    "source_site", "raw_meta",
)
RELEASE_COLUMNS = (
    "post_canonical_key", "label", "quality", "resolution", "size_bytes", "codec",
    "season_number", "episode_number", "audio_languages", "bridge_url", "origin_url",
)
SOURCE_COLUMNS = (
    "release_id", "source_name", "service", "resource_id", "source_url", "final_url",
    "playback_type", "status", "is_temporary", "quality", "last_checked",
)
INTEGER_COLUMNS = frozenset({
    "year", "is_18_plus", "is_animated", "scraped", "error_count", "size_bytes",
    "season_number", "episode_number", "is_temporary", "last_checked",
})

_SCHEMA_TABLES = """
CREATE TABLE IF NOT EXISTS sitemap_cache (
    loc TEXT PRIMARY KEY,
    lastmod TEXT,
    slug TEXT,
    scraped INTEGER DEFAULT 0,
    raw_json TEXT,
    error_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS taxonomy_cache (
    id INTEGER PRIMARY KEY,
    name TEXT,
    fetched_at INTEGER
);

CREATE TABLE IF NOT EXISTS posts (
    canonical_key TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    clean_title TEXT NOT NULL,
    year INTEGER,
    media_type TEXT,
    poster_url TEXT,
    backdrop_url TEXT,
    backdrop_urls TEXT,
    imdb_id TEXT,
    tmdb_id TEXT,
    imdb_rating TEXT,
    synopsis TEXT,
    genres TEXT,
    director TEXT,
    cast_names TEXT,
    duration TEXT,
    release_date TEXT,
    languages TEXT,
    industry TEXT,
    country TEXT,
    seasons TEXT,
    url TEXT,
    slug TEXT,
    is_18_plus INTEGER DEFAULT 0,
    is_animated INTEGER DEFAULT 0,
    source_site TEXT DEFAULT 'moviesmela',
    scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    raw_meta TEXT
);

CREATE TABLE IF NOT EXISTS releases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_canonical_key TEXT NOT NULL,
    label TEXT,
    quality TEXT,
    resolution TEXT,
    size_bytes INTEGER,
    codec TEXT,
    season_number INTEGER,
    episode_number INTEGER,
    audio_languages TEXT,
    bridge_url TEXT,
    origin_url TEXT,
    FOREIGN KEY (post_canonical_key) REFERENCES posts(canonical_key)
);

CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    release_id INTEGER NOT NULL,
    source_name TEXT,
    service TEXT,
    resource_id TEXT,
    source_url TEXT,
    final_url TEXT,
    playback_type TEXT DEFAULT 'iframe',
    status TEXT DEFAULT 'unverified',
    is_temporary INTEGER DEFAULT 0,
    quality TEXT,
    last_checked INTEGER,
    FOREIGN KEY (release_id) REFERENCES releases(id)
);

"""

_SCHEMA_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_moviesmela_posts_slug ON posts(slug);
CREATE INDEX IF NOT EXISTS idx_moviesmela_posts_type ON posts(media_type);
CREATE INDEX IF NOT EXISTS idx_moviesmela_sources_status ON sources(status);
CREATE INDEX IF NOT EXISTS idx_moviesmela_sources_playback ON sources(playback_type);
CREATE INDEX IF NOT EXISTS idx_moviesmela_releases_post ON releases(post_canonical_key);
"""


def _add_missing_columns(conn: sqlite3.Connection, table: str, wanted) -> None:
    have = {c[1] for c in conn.execute(f"PRAGMA table_info({table});").fetchall()}
    for col in wanted:
        if col in have:
            continue
        decl = "INTEGER" if col in INTEGER_COLUMNS else "TEXT"
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl};")


def ensure_schema(conn: sqlite3.Connection) -> None:
    """
    Creates the staging shape and the taxonomy cache, and hands the caller back
    a row factory: every reader in this module addresses columns by name.
    """
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA_TABLES)
    _add_missing_columns(conn, "posts", POST_COLUMNS + ("scraped_at",))
    _add_missing_columns(conn, "releases", RELEASE_COLUMNS)
    _add_missing_columns(conn, "sources", SOURCE_COLUMNS)
    conn.executescript(_SCHEMA_INDEXES)


def _merge_raw_meta(existing: str | None, page_meta: dict, page_url: str) -> dict:
    """
    Keeps one row per work while keeping every page's own evidence.

    `raw_meta.pages` accumulates the per-page records; the scalars of the newest
    write win, because they describe the work rather than the print.
    """
    merged = {}
    if existing:
        try:
            loaded = json.loads(existing)
        except json.JSONDecodeError:
            loaded = None
        if isinstance(loaded, dict):
            merged.update(loaded)
    pages = merged.get("pages")
    if not isinstance(pages, dict):
        pages = {}
    pages[page_url] = page_meta
    merged["pages"] = pages
    merged["page_count"] = len(pages)
    merged.setdefault("site", SITE)
    merged["last_page_url"] = page_url
    for key, value in page_meta.items():
        if key not in ("page", "players", "media_type", "release_label"):
            merged.setdefault(key, value)
    return merged


def export_staging(db_path: Path | str = DEFAULT_DB_PATH, posts=()) -> dict:
    """
    Commits parsed page records into the isolated staging database.

    Idempotent and additive across a show's pages: a re-scraped page replaces
    only the releases whose origin_url is that page, so a resumed crawl never
    deletes another episode's prints.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    totals = {"posts_written": 0, "releases_written": 0, "sources_written": 0,
              "skipped": 0}
    conn = sqlite3.connect(db_path, timeout=60)
    conn.row_factory = sqlite3.Row
    try:
        ensure_schema(conn)
        for post in posts or ():
            if not post or not post.get("clean_title") or not post.get("canonical_key"):
                totals["skipped"] += 1
                continue
            releases = post.get("releases") or []
            if not releases:
                totals["skipped"] += 1
                continue
            cls = classify(post)
            page_meta = post.get("raw_meta") or {}
            existing = conn.execute(
                "SELECT raw_meta FROM posts WHERE canonical_key = ?;",
                (post["canonical_key"],)).fetchone()
            merged = _merge_raw_meta(
                existing["raw_meta"] if existing else None, page_meta,
                post.get("url") or "")
            row = {
                "canonical_key": post["canonical_key"],
                "title": post["clean_title"],
                "clean_title": post["clean_title"],
                "year": post.get("year"),
                "media_type": post.get("media_type")
                              if post.get("media_type") in LEGAL_MEDIA_TYPES
                              else "movie",
                "poster_url": post.get("poster_url"),
                "backdrop_url": post.get("backdrop_url"),
                "backdrop_urls": post.get("backdrop_urls"),
                "imdb_id": post.get("imdb_id"),
                "tmdb_id": post.get("tmdb_id"),
                "imdb_rating": post.get("imdb_rating"),
                "synopsis": post.get("synopsis"),
                "genres": post.get("genres"),
                "director": post.get("director"),
                "cast_names": post.get("cast_names"),
                "duration": post.get("duration"),
                "release_date": post.get("release_date"),
                "languages": post.get("languages"),
                "industry": cls["industry"],
                "country": cls["country"],
                "seasons": post.get("seasons"),
                "url": post.get("url"),
                "slug": post.get("slug"),
                "is_18_plus": int(post.get("is_18_plus") or 0),
                "is_animated": int(post.get("is_animated") or 0),
                "source_site": SITE,
                "raw_meta": json.dumps(merged, ensure_ascii=False),
            }
            placeholders = ", ".join(f":{c}" for c in POST_COLUMNS)
            updates = ", ".join(
                f"{c} = COALESCE(excluded.{c}, posts.{c})"
                for c in POST_COLUMNS
                if c not in ("canonical_key", "title", "clean_title",
                             "url", "slug", "source_site", "raw_meta",
                             "media_type", "year", "is_18_plus", "is_animated"))
            conn.execute(
                f"""
                INSERT INTO posts ({", ".join(POST_COLUMNS)}) VALUES ({placeholders})
                ON CONFLICT(canonical_key) DO UPDATE SET
                    title = excluded.title,
                    clean_title = excluded.clean_title,
                    media_type = CASE WHEN posts.media_type = 'movie'
                                      THEN excluded.media_type
                                      ELSE posts.media_type END,
                    url = excluded.url,
                    slug = excluded.slug,
                    source_site = excluded.source_site,
                    raw_meta = excluded.raw_meta,
                    year = COALESCE(posts.year, excluded.year),
                    is_18_plus = MAX(posts.is_18_plus, excluded.is_18_plus),
                    is_animated = MAX(posts.is_animated, excluded.is_animated),
                    {updates},
                    scraped_at = CURRENT_TIMESTAMP;
                """,
                row,
            )
            totals["posts_written"] += 1

            page_url = post.get("url")
            stale = [r["id"] for r in conn.execute(
                "SELECT id FROM releases WHERE post_canonical_key = ?"
                " AND origin_url = ?", (post["canonical_key"], page_url)).fetchall()]
            if stale:
                conn.executemany("DELETE FROM sources WHERE release_id = ?;",
                                 [(i,) for i in stale])
                conn.executemany("DELETE FROM releases WHERE id = ?;",
                                 [(i,) for i in stale])

            for rel in releases:
                cur = conn.execute(
                    f"INSERT INTO releases ({', '.join(RELEASE_COLUMNS)})"
                    f" VALUES ({', '.join('?' * len(RELEASE_COLUMNS))});",
                    (post["canonical_key"], rel.get("label"), rel.get("quality"),
                     rel.get("resolution"), rel.get("size_bytes"), rel.get("codec"),
                     rel.get("season_number"), rel.get("episode_number"),
                     rel.get("audio_languages"), rel.get("bridge_url"), page_url),
                )
                totals["releases_written"] += 1
                for src in sources_for(rel):
                    conn.execute(
                        f"INSERT INTO sources ({', '.join(SOURCE_COLUMNS)})"
                        f" VALUES ({', '.join('?' * len(SOURCE_COLUMNS))});",
                        (cur.lastrowid, src.get("source_name"), src.get("service"),
                         src.get("resource_id"), src.get("source_url"),
                         src.get("final_url") or src.get("source_url"),
                         src.get("playback_type", "iframe"),
                         src.get("status", DEFAULT_SOURCE_STATUS),
                         int(src.get("is_temporary") or 0),
                         src.get("quality") or rel.get("quality"),
                         src.get("last_checked")),
                    )
                    totals["sources_written"] += 1

            if page_url:
                # `raw_json` is only ever written on a fresh insert. The queue
                # row's REST payload is what makes a re-crawl a local transform;
                # overwriting it with this page's parse result would leave every
                # later pass no choice but to ask the site for the post again.
                conn.execute(
                    """
                    INSERT INTO sitemap_cache (loc, lastmod, slug, scraped, raw_json, error_count)
                    VALUES (?, ?, ?, 1, ?, 0)
                    ON CONFLICT(loc) DO UPDATE SET scraped = 1, slug = excluded.slug,
                        lastmod = excluded.lastmod;
                    """,
                    (page_url, post.get("lastmod"), row["slug"],
                     json.dumps(page_meta, ensure_ascii=False)),
                )
        conn.commit()
    finally:
        conn.close()
    return totals


# ---------------------------------------------------------------------------
# Queue and crawl
# ---------------------------------------------------------------------------


def _queue_json(wp_post: dict) -> dict:
    """
    The whole reason the crawl needs no network: content.rendered travels with
    the queue row, so players are parsed locally and only --probe opens a socket.
    """
    return {
        "id": wp_post.get("id"), "slug": wp_post.get("slug"),
        "link": wp_post.get("link"), "title": wp_post.get("title"),
        "excerpt": wp_post.get("excerpt"), "content": wp_post.get("content"),
        "date": wp_post.get("date"), "modified": wp_post.get("modified"),
        "categories": wp_post.get("categories"), "tags": wp_post.get("tags"),
        "yoast_head_json": {k: v for k, v in (wp_post.get("yoast_head_json") or {}).items()
                            if k in ("og_image", "og_description", "title")},
    }


def load_taxonomy(db_path: Path | str | None = None) -> dict[int, str]:
    """
    One id -> name map for all categories, in TAXONOMY_PAGE_CAP requests or fewer.

    Cached in a side table so a re-sync costs nothing: 275 names for the whole
    catalog is the cheapest taxonomy read available.
    """
    mapping: dict[int, str] = {}
    page = 1
    while page <= TAXONOMY_PAGE_CAP:
        status, payload = get_json(
            f"{REST_CATEGORIES}?per_page=100&page={page}&orderby=id&order=asc")
        if status != 200 or not isinstance(payload, list) or not payload:
            break
        for term in payload:
            if isinstance(term, dict) and term.get("id") is not None:
                mapping[int(term["id"])] = _clean_text(
                    (term.get("name") or {}).get("rendered")
                    if isinstance(term.get("name"), dict) else term.get("name")) or ""
        if len(payload) < 100:
            break
        page += 1
    if db_path is not None:
        conn = sqlite3.connect(Path(db_path), timeout=60)
        try:
            ensure_schema(conn)
            conn.executemany(
                "INSERT OR REPLACE INTO taxonomy_cache (id, name, fetched_at)"
                " VALUES (?, ?, ?);",
                [(i, n, int(time.time())) for i, n in mapping.items()])
            conn.commit()
        finally:
            conn.close()
    return mapping


def cached_taxonomy(db_path: Path | str) -> dict[int, str]:
    path = Path(db_path)
    if not path.exists():
        return {}
    conn = sqlite3.connect(path, timeout=60)
    try:
        ensure_schema(conn)
        rows = conn.execute("SELECT id, name FROM taxonomy_cache;").fetchall()
        return {int(r["id"]): (r["name"] or "") for r in rows}
    finally:
        conn.close()


def iter_catalog_posts():
    """Pages the REST collection, bounded by MAX_PAGES and by a short page."""
    page = 1
    while page <= MAX_PAGES:
        if STOP_REQUESTED:
            return
        url = f"{REST_POSTS}?per_page={PAGE_SIZE}&page={page}&orderby=id&order=asc"
        status, payload = get_json(url, timeout=LISTING_TIMEOUT)
        if status != 200:
            print(f"[!] [{SITE}] page {page} -> HTTP {status}", flush=True)
            return
        if payload is None:
            print(f"[!] [{SITE}] page {page} returned a body that is not JSON",
                  flush=True)
            return
        if not isinstance(payload, list):
            print(f"[!] [{SITE}] page {page} is not a post list", flush=True)
            return
        if not payload:
            return
        for wp_post in payload:
            yield wp_post
        if len(payload) < PAGE_SIZE:
            return
        page += 1


def sync_catalog(limit: int | None = None, db_path: Path | str = DEFAULT_DB_PATH,
                 verbose: bool = True, batch_size: int = QUEUE_FLUSH_BATCH) -> int:
    """
    Queues every catalog entry with its own REST record attached.

    A row the site still lists is always worth another attempt, so an
    already-indexed row whose `modified` moved is set to re-check (2) and a
    parked row (-1) is set back to queued (0).

    The queue is written while it is read, `batch_size` rows per commit, because
    this site's real collection is 20,888 posts over 1,045 REST pages (measured
    2026-10-28) and every record carries its own `content.rendered`. Collecting
    the pass before the first INSERT held 10,460 of those page bodies in RAM at
    once (57 MB of resident set at 335 s, still climbing) on a host with 2.5 GB
    free and other agents' crawlers on it — and the old shape committed only at
    the end, so a stop late in the pass lost every page it had read.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    taxonomy = load_taxonomy(db_path)
    if not taxonomy:
        if verbose:
            print(f"[!] [{SITE}] taxonomy unavailable; nothing queued.", flush=True)
        return 0

    conn = sqlite3.connect(db_path, timeout=60)
    seen: set[str] = set()
    count = staged = new_rows = 0
    try:
        ensure_schema(conn)
        prior = {r["loc"]: (r["lastmod"] or "", r["scraped"])
                 for r in conn.execute("SELECT loc, lastmod, scraped FROM sitemap_cache")}
        before = len(prior)
        for wp_post in iter_catalog_posts():
            link = _normalize_http_url(wp_post.get("link") or "")
            if not link or not _is_site_url(link) or link in seen:
                continue
            seen.add(link)
            lastmod = wp_post.get("modified") or ""
            scraped = 0
            if link in prior:
                old_lastmod, old_state = prior[link]
                if old_state == 1 and lastmod and lastmod != old_lastmod:
                    scraped = 2          # the site edited the page: re-check it
                elif old_state == 1:
                    scraped = 1          # already indexed and unchanged
            else:
                new_rows += 1
            conn.execute(
                """
                INSERT INTO sitemap_cache (loc, lastmod, slug, scraped, raw_json, error_count)
                VALUES (?, ?, ?, ?, ?, 0)
                ON CONFLICT(loc) DO UPDATE SET lastmod = excluded.lastmod,
                    slug = excluded.slug, raw_json = excluded.raw_json,
                    scraped = excluded.scraped;
                """,
                (link, lastmod, wp_post.get("slug") or "", scraped,
                 json.dumps(_queue_json(wp_post), ensure_ascii=False)),
            )
            count += 1
            if limit and count >= limit:
                break
            staged += 1
            if staged >= batch_size:
                conn.commit()
                staged = 0
        conn.execute("UPDATE sitemap_cache SET scraped = 0 WHERE scraped = -1;")
        conn.commit()
        queued = conn.execute(
            "SELECT COUNT(*) FROM sitemap_cache WHERE scraped IN (0, 2)").fetchone()[0]
        after = conn.execute("SELECT COUNT(*) FROM sitemap_cache").fetchone()[0]
    finally:
        conn.close()
    if verbose:
        if not count:
            print("[!] No catalog entries returned; nothing queued.", flush=True)
        else:
            print(f"[✓] [{SITE}] Queued {count} pages ({new_rows} new, "
                  f"{after} known, {queued} pending).", flush=True)
    return after - before


def _fetch_post_by_slug(slug: str) -> dict | None:
    """
    Recovery path for a queue row without an embedded record (the legacy shape,
    or a row parked by an older build).
    """
    status, payload = get_json(
        f"{REST_POSTS}?slug={urllib.parse.quote(slug or '')}")
    if isinstance(payload, list) and payload:
        return payload[0]
    return None


def _parse_record(loc: str, raw_json: str | None, slug: str,
                  taxonomy: dict[int, str]) -> tuple[dict | None, str]:
    wp_post = None
    if raw_json:
        try:
            candidate = json.loads(raw_json)
        except json.JSONDecodeError:
            candidate = None
        if isinstance(candidate, dict) and "id" in candidate:
            wp_post = candidate
    if wp_post is None:
        wp_post = _fetch_post_by_slug(slug)
        if wp_post is None:
            return None, "not-a-post"
    post = build_post(wp_post, taxonomy)
    if post is None:
        return None, "no-players"
    if post.get("url") and loc and post["url"] != loc:
        post["url"] = loc
    return post, "ok"


def _bump_error(db_path: Path, loc: str, note: str, park_now: bool = False,
                requeue: bool = False) -> None:
    """
    Records why a page did not become a row: park on the first sighting when the
    site itself says the page is gone, spend the three-strike budget otherwise.
    """
    if not loc:
        return
    conn = sqlite3.connect(db_path, timeout=60)
    try:
        ensure_schema(conn)
        stored = conn.execute(
            "SELECT raw_json FROM sitemap_cache WHERE loc = ?;", (loc,)).fetchone()
        stamp = {"last_note": note, "at": int(time.time())}
        try:
            record = json.loads(stored[0]) if stored and stored[0] else None
        except json.JSONDecodeError:
            record = None
        if isinstance(record, dict) and "id" in record:
            record.update(stamp)
        else:
            record = stamp
        conn.execute(
            "UPDATE sitemap_cache SET error_count = error_count + 1, raw_json = ?"
            " WHERE loc = ?;",
            (json.dumps(record, ensure_ascii=False), loc))
        conn.execute(
            """UPDATE sitemap_cache SET scraped = CASE
                   WHEN ? THEN -1
                   WHEN ? THEN 2
                   WHEN error_count >= 3 THEN -1
                   ELSE scraped
               END
               WHERE loc = ?;""",
            (1 if park_now else 0, 1 if requeue else 0, loc))
        conn.commit()
    finally:
        conn.close()


def crawl_pending(limit: int | None = None, db_path: Path | str = DEFAULT_DB_PATH,
                  workers: int = 4, probe: bool = False, deep: bool = False,
                  delay: float = 0.2, batch_size: int = 40,
                  verbose: bool = True) -> dict:
    """
    Parses and commits every queued page.

    With probe off this is a local transform of what sync already downloaded: no
    socket at all. With --probe it is one request per player, and its only effect
    is the status column — an iframe never becomes a byte endpoint.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    taxonomy = cached_taxonomy(db_path) or load_taxonomy(db_path)
    conn = sqlite3.connect(db_path, timeout=60)
    conn.row_factory = sqlite3.Row
    try:
        ensure_schema(conn)
        rows = conn.execute(PENDING_SELECT, QUEUED_SCRAPE_STATES).fetchall()
    finally:
        conn.close()
    if limit:
        rows = rows[:limit]
    if verbose:
        print(f"[*] [{SITE}] {len(rows)} pages pending "
              f"(workers={workers}, probe={probe}, deep={deep}).", flush=True)

    totals = {"pages": 0, "posts": 0, "releases": 0, "sources": 0,
              "not_indexable": 0, "failed": 0}
    if not rows:
        return totals

    def work(row):
        if STOP_REQUESTED:
            return None
        if not taxonomy:
            return None, "no-taxonomy"
        _sleep(delay)
        post, verdict = _parse_record(row["loc"], row["raw_json"], row["slug"], taxonomy)
        if post is None:
            return None, verdict
        try:
            return resolve_links(post, probe=probe, deep=deep), verdict
        except Exception as exc:      # a dead probe must not lose the catalog row
            post["resolve_error"] = str(exc)
            return post, verdict

    batch: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        future_to_row = {pool.submit(work, r): r for r in rows}
        done = 0
        for fut in concurrent.futures.as_completed(future_to_row):
            queued = future_to_row[fut]
            done += 1
            try:
                outcome = fut.result()
            except Exception as exc:
                totals["failed"] += 1
                _bump_error(db_path, queued["loc"], f"exception: {exc}")
                continue
            if outcome is None:
                continue              # drained before this row was touched
            totals["pages"] += 1
            post, verdict = outcome
            if post is None:
                totals["not_indexable"] += 1
                _bump_error(db_path, queued["loc"], verdict,
                            park_now=verdict in ("not-a-post", "no-taxonomy"),
                            requeue=verdict == "no-players")
                continue
            batch.append(post)
            if len(batch) >= batch_size:
                _flush(db_path, batch, totals)
                batch = []
            if verbose and (done == len(rows) or done % 500 == 0):
                print(f"    ... {done}/{len(rows)} pages, {totals['sources']} sources",
                      flush=True)
            if STOP_REQUESTED:
                break
        _flush(db_path, batch, totals)

    if verbose:
        print(f"[✓] [{SITE}] pages={totals['pages']} works={totals['posts']} "
              f"releases={totals['releases']} sources={totals['sources']} "
              f"declined={totals['not_indexable']} failed={totals['failed']}",
              flush=True)
    return totals


def _flush(db_path: Path, batch: list[dict], totals: dict) -> None:
    if not batch:
        return
    written = export_staging(db_path, batch)
    totals["posts"] += written["posts_written"]
    totals["releases"] += written["releases_written"]
    totals["sources"] += written["sources_written"]
    totals["not_indexable"] += written["skipped"]
    batch.clear()


def parse_page(html_or_url: str, url: str | None = None) -> dict | None:
    """One page, from its URL — the CLI's `parse`/`resolve` entry point."""
    target = html_or_url if isinstance(html_or_url, str) else str(html_or_url)
    if not target.startswith("http"):
        return None
    slug = urllib.parse.unquote(
        urllib.parse.urlsplit(target).path.strip("/").split("/")[-1])
    if not slug:
        return None
    taxonomy = load_taxonomy()
    wp_post = _fetch_post_by_slug(slug)
    if wp_post is None:
        return None
    post, _verdict = _parse_record(url or target, json.dumps(wp_post), slug, taxonomy)
    return post


def get_stats(db_path: Path | str = DEFAULT_DB_PATH) -> dict:
    conn = sqlite3.connect(Path(db_path), timeout=60)
    conn.row_factory = sqlite3.Row
    try:
        ensure_schema(conn)
        posts = conn.execute("SELECT COUNT(*) c FROM posts").fetchone()["c"]
        iframe_rows = conn.execute(
            "SELECT COUNT(*) c FROM sources WHERE playback_type = 'iframe'").fetchone()["c"]
        return {
            "site": SITE,
            "queued": conn.execute(
                "SELECT COUNT(*) c FROM sitemap_cache WHERE scraped IN (0,2)").fetchone()["c"],
            "indexed": conn.execute(
                "SELECT COUNT(*) c FROM sitemap_cache WHERE scraped = 1").fetchone()["c"],
            "parked": conn.execute(
                "SELECT COUNT(*) c FROM sitemap_cache WHERE scraped = -1").fetchone()["c"],
            "pages_seen": conn.execute("SELECT COUNT(*) c FROM sitemap_cache").fetchone()["c"],
            "posts": posts,
            "media_types": dict(conn.execute(
                "SELECT media_type, COUNT(*) FROM posts GROUP BY media_type").fetchall()),
            "adult_flagged": conn.execute(
                "SELECT COUNT(*) c FROM posts WHERE is_18_plus = 1").fetchone()["c"],
            "with_year": conn.execute(
                "SELECT COUNT(*) c FROM posts WHERE year IS NOT NULL").fetchone()["c"],
            "with_poster": conn.execute(
                "SELECT COUNT(*) c FROM posts WHERE poster_url IS NOT NULL").fetchone()["c"],
            "with_synopsis": conn.execute(
                "SELECT COUNT(*) c FROM posts WHERE synopsis IS NOT NULL").fetchone()["c"],
            "episodes": conn.execute(
                "SELECT COUNT(*) c FROM releases WHERE episode_number IS NOT NULL").fetchone()["c"],
            "releases": conn.execute("SELECT COUNT(*) c FROM releases").fetchone()["c"],
            "sources": conn.execute("SELECT COUNT(*) c FROM sources").fetchone()["c"],
            # Counted apart so an iframe page count can never be read as
            # "watchable links". `resolvable_rows` is the two hosts (mxdrop,
            # pkembed) whose stored embed URL a stdlib resolver turns into a
            # signed mp4 on demand; `direct_byte_rows` would be a row that
            # already IS a byte endpoint, and on this site that is always zero.
            "iframe_rows": iframe_rows,
            "resolvable_rows": conn.execute(
                "SELECT COUNT(*) c FROM sources WHERE playback_type = 'url'").fetchone()["c"],
            "subtitle_rows": conn.execute(
                "SELECT COUNT(*) c FROM sources WHERE playback_type = 'subtitle'").fetchone()["c"],
            "download_rows": conn.execute(
                "SELECT COUNT(*) c FROM sources WHERE playback_type = 'download'").fetchone()["c"],
            "direct_byte_rows": conn.execute(
                "SELECT COUNT(*) c FROM sources WHERE playback_type IN "
                "('stream','hls','direct')").fetchone()["c"],
            "source_status": dict(conn.execute(
                "SELECT status, COUNT(*) FROM sources GROUP BY status").fetchall()),
            "services": dict(conn.execute(
                "SELECT service, COUNT(*) FROM sources GROUP BY service"
                " ORDER BY COUNT(*) DESC").fetchall()),
            "countries": dict(conn.execute(
                "SELECT country, COUNT(*) FROM posts GROUP BY country"
                " ORDER BY COUNT(*) DESC").fetchall()),
            "industries": dict(conn.execute(
                "SELECT industry, COUNT(*) FROM posts GROUP BY industry"
                " ORDER BY COUNT(*) DESC").fetchall()),
            "integrity": conn.execute("PRAGMA integrity_check").fetchone()[0],
        }
    finally:
        conn.close()


def stats(db_path: Path | str = DEFAULT_DB_PATH) -> dict:
    return get_stats(db_path)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="import_moviesmela.py",
        description=f"moviesmela staging importer ({BASE_URL} -> {DEFAULT_DB_PATH})")
    parser.add_argument("command", nargs="?", default="sync",
                        choices=["sync", "crawl", "parse", "resolve", "stats"])
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--delay", type=float, default=0.2)
    parser.add_argument("--batch-size", type=int, default=40, dest="batch_size")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--url", help="single page URL for parse/resolve")
    parser.add_argument("--probe", action="store_true",
                        help="open every player page and record what it answered "
                             "(one request per player; never turns an iframe into a stream)")
    parser.add_argument("--deep", action="store_true",
                        help="with --probe, also store the redirect target as final_url")
    parser.add_argument("--quiet", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    db = Path(args.db)
    verbose = not args.quiet

    if args.command == "sync":
        sync_catalog(limit=args.limit, db_path=db, verbose=verbose)
    elif args.command == "crawl":
        crawl_pending(limit=args.limit, db_path=db, workers=args.workers,
                      probe=args.probe, deep=args.deep, delay=args.delay,
                      batch_size=args.batch_size, verbose=verbose)
    elif args.command == "stats":
        print(json.dumps(get_stats(db), indent=2, ensure_ascii=False))
        return 0
    else:
        if not args.url:
            parser.error(f"{args.command} requires --url")
        post = parse_page(args.url)
        if post is None:
            print("[!] Page is not a catalog entry.", file=sys.stderr)
            return 1
        if args.command == "resolve":
            post = resolve_links(post, probe=True, deep=args.deep)
        print(json.dumps(post, indent=2, ensure_ascii=False))
    return 0


_install_signal_handlers()


if __name__ == "__main__":
    sys.exit(main())
