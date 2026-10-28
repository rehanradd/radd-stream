#!/usr/bin/env python3
"""
DesiSerials staging importer — https://desiserials.watch -> desiserials.db

What this site is, measured on 2026-10-28
-----------------------------------------
A WordPress (theme: sahifa) catalogue of Indian and Pakistani daily serials. The
public REST collection answers with `X-WP-Total: 3646` posts, and the unit of
publication is not a series page but a single episode:

    title    "Kaun Banega Crorepati 18 28th October 2026 Full Episode 58 Watch Online"
    category one term, and that term IS the series ("Kaun Banega Crorepati 18")
    author   one term, and that term IS the network ("Sonyliv", "Zee5", "JioHotstar")
    content  a boilerplate paragraph plus `Serial Name:` / `Media Owner:` / `Media By:`
    media    `wp:featuredmedia` present on 100/100 sampled posts

The rendered page adds the one thing the REST record does not carry: the player.
Measured across four episode pages, `post_content` holds zero iframes while the
served HTML holds exactly one — the theme injects it — so metadata comes from the
collection and the player comes from a page fetch. Same two-stage shape as the
AnimaHD importer: `sync` queues from REST, `crawl` fetches one page per episode.

What becomes a source row, and what does not
--------------------------------------------
Every player here is an `<iframe>` of a third-party host, published in plaintext:

    //vkspeed.com/embed-8i6f58m6to0g.html      (VKspeed/VKprime, the common case)
    https://upbolt.to/emb-y1q5jqsfgotr         (measured: answers 403, Cloudflare
                                                "Just a moment" challenge)

Neither host is implemented in `host_resolvers`, and this module does not pretend
otherwise. `playback_type` is therefore `iframe` for every row, which `viewer.py`
maps to `kind='external'`, `playable=false`: catalog evidence, never a promise.
Measured and recorded for whoever picks this up next: the vkspeed embed document
carries a Dean-Edwards packed script (`eval(function(p,a,c,k,e,d)`), the same
family the mxdrop unpacker already handles, while upbolt is behind a JS challenge
and this project ships no browser and no challenge-solver.

The embed URL is the durable identifier — `embed-<id>.html` / `emb-<id>` — so it
is stored verbatim, and `is_temporary=0`. A resolved byte URL, if one is ever
produced, belongs to that call and is never written here. No Referer is attached
to any media request: the site's own pages need none, and an embed host that
demands one is refusing, not being helped.

Why the staging write is an upsert, not a replacement
-----------------------------------------------------
AnimaHD owns one page per post, so a re-crawl replaces that post's releases
wholesale. Here 3,646 queue rows share ~31 series rows: replacing wholesale would
leave each series holding only the last episode crawled. `export_staging`
therefore writes one release per episode, keyed by (series, origin_url), and
touches nothing else.

Stdlib only. Staging only: the default path is
/home/ubuntu/radd-stream-data/desiserials.db and this module never opens a
database other than the one it is given.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import html
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

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = Path("/home/ubuntu/radd-stream-data/desiserials.db")

SITE = "desiserials"
BASE_URL = "https://desiserials.watch"
REST_POSTS = f"{BASE_URL}/wp-json/wp/v2/posts"
USER_AGENT = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

PAGE_SIZE = 100
MAX_PAGES = 60                 # X-WP-TotalPages is 37 at per_page=100 (2026-10-28)
LISTING_TIMEOUT = 60
PAGE_TIMEOUT = 45
RETRY_BACKOFF = 2.0
MAX_RETRIES = 3

QUEUED_SCRAPE_STATES = (0, 2)
DEFAULT_SOURCE_STATUS = "unverified"
LEGAL_MEDIA_TYPES = frozenset({"movie", "series"})

# The player hosts this catalogue was measured publishing. Anything else that
# appears inside an <iframe> on a page is an advertisement and is dropped:
# a scraper that stores every iframe it finds is a scraper that stores ad
# trackers as "sources".
PLAYER_HOST_RE = re.compile(
    r"(?:^|\.)(?:vkspeed|vkprime|vkseed|upbolt|streamkit|hubvideo|desiash)"
    r"\.(?:com|to|net|xyz|club|video|fun)$", re.I)
PLAYER_PATH_RE = re.compile(r"^/(?:embed-|emb-|e/|v/|embed/)[A-Za-z0-9_-]{6,}", re.I)
SITE_HOST_RE = re.compile(r"(?:^|\.)desiserials\.(?:watch|cc|com)$", re.I)
TRACKER_HOST_RE = re.compile(
    r"(?:^|\.)(?:googletagmanager|google-analytics|doubleclick|facebook|ct\.[a-z]+|"
    r"[a-z]+\.cloudflarestorage|adsterra|propellerads|juicyads|exoclick|popads)\.", re.I)

ALLOWED_SOURCE_HOST_RE = re.compile(
    r"(?:^|\.)(?:desiserials\.watch|vkspeed\.com|vkprime\.com|upbolt\.to)$", re.I)

EPISODE_RE = re.compile(
    r"Full Episode\s+(?P<episode>\d{1,4})|Episode\s+(?P<episode_alt>\d{1,4})", re.I)
AIR_DATE_RE = re.compile(
    r"(?P<day>3[01]|2\d|1\d|[1-9])(?:st|nd|rd|th)?\s+"
    r"(?P<month>January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+(?P<year>(?:19|20)\d{2})", re.I)
SEASON_RE = re.compile(r"\bSeason\s+(?P<season>\d{1,2})\b", re.I)
MOVIE_RE = re.compile(r"\b(?:Full\s+)?Movie\b", re.I)
YEAR_PAREN_RE = re.compile(r"\((?P<year>(?:19|20)\d{2})\)")

BRAND_TOKEN_RE = re.compile(r"\[[^\]\[]{0,30}desi\s*serials?[^\]\[]{0,30}\]", re.I)
SEO_SUFFIX_RE = re.compile(
    r"\s*(?:Watch\s+Online(?:\s+All\s+Episodes)?(?:\s+HD)?|Watch\s+(?:HD|Online)|"
    r"Online\s+Free\s+Download|Web-Dl|Full\s+Episodes?)\s*$", re.I)
# `18+` must be matched outside the word-boundary group: a trailing \b after the
# plus cannot exist when the next character is `)` or a space, which is how the
# token actually appears in a title ("Foo (18+)", "Foo 18+ Cut").
MATURE_TOKEN_RE = re.compile(
    r"\b(?:hentai|porn|xxx|netorare|shota|loli|nc-17|erotic|adult)\b|18\s*\+", re.I)

# `Serial Name:` / `Media Owner:` / `Media By:` are the only labeled fields the
# content block publishes (100/100, 100/100, 92/100 sampled).
FIELD_RE = re.compile(
    r"<strong>\s*(?P<label>Serial Name|Media Owner|Media By)\s*:?\s*</strong>\s*"
    r"(?P<value>[\s\S]{1,140}?)(?=<(?:br|/p|strong>)|\Z)", re.I)
IFRAME_RE = re.compile(r"<iframe\b[^>]*?src=(?P<quote>[\"'])(?P<src>[^\"']+)(?P=quote)[^>]*>",
                       re.I | re.S)
OG_IMAGE_RE = re.compile(r"<meta\s+property=[\"']og:image[\"']\s+content=[\"'](?P<url>[^\"']+)",
                         re.I)
ENTRY_TEXT_RE = re.compile(r"<div\s+class=[\"'][^\"']*entry-content[^\"']*[\"'][\s\S]*?"
                           r"</div>", re.I)
IMAGE_EXT_RE = re.compile(r"\.(?:jpe?g|png|webp|avif)(?:[?#].*)?$", re.I)

LANGUAGE_TOKENS = {
    "hindi": "Hindi", "urdu": "Urdu", "punjabi": "Punjabi", "tamil": "Tamil",
    "telugu": "Telugu", "malayalam": "Malayalam", "kannada": "Kannada",
    "bengali": "Bengali", "marathi": "Marathi", "gujarati": "Gujarati",
    "english": "English", "bhojpuri": "Bhojpuri",
}

# Networks the site credits as `Media Owner` / author. Country comes from the
# publisher the site itself names, not from a guess about the title.
NETWORK_COUNTRY = {
    "sonyliv": ("India", "SonyLIV"), "sony tv": ("India", "Sony TV"),
    "sab tv": ("India", "SAB TV"), "set max": ("India", "SET Max"),
    "zee5": ("India", "ZEE5"), "zee tv": ("India", "Zee TV"),
    "zee marathi": ("India", "Zee Marathi"),
    "jiohotstar": ("India", "JioHotstar"), "jiocinema": ("India", "JioCinema"),
    "star plus": ("India", "Star Plus"), "star Bharat": ("India", "Star Bharat"),
    "colors": ("India", "Colors TV"), "colors tv": ("India", "Colors TV"),
    "real tvc": ("India", "Real TV"),
    "hum tv": ("Pakistan", "Hum TV"), "ary digital": ("Pakistan", "ARY Digital"),
    "geo tv": ("Pakistan", "Geo TV"), "green tv": ("Pakistan", "Green TV"),
    "urdu1": ("Pakistan", "URDU1"), "samaa tv": ("Pakistan", "Samaa TV"),
    "a-ware broadcaster": ("Pakistan", "A-Plus"), "ptv global": ("Pakistan", "PTV"),
}

STOP_REQUESTED = False


def _signal_handler(signum, frame):
    global STOP_REQUESTED
    STOP_REQUESTED = True
    print(f"\n[!] [{SITE}] signal {signum}: finishing the rows already in flight, "
          f"then stopping. Run again to resume.", flush=True)


def _install_signal_handlers() -> bool:
    try:
        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)
    except ValueError:
        return False
    return True


# ---------------------------------------------------------------------------
# Transport: one socket primitive, behind a seam every test replaces
# ---------------------------------------------------------------------------

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _build_ssl_context() -> ssl.SSLContext:
    """Verification is never turned off: a catalog row is not worth a MITM."""
    return ssl.create_default_context()


def _build_openers(context: ssl.SSLContext):
    follow = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=context),
        urllib.request.HTTPRedirectHandler())
    strict = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=context), _NoRedirect())
    for opener in (follow, strict):
        opener.addheaders = [("User-Agent", USER_AGENT),
                             ("Accept", "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8"),
                             ("Accept-Language", "en-US,en;q=0.5")]
    return follow, strict


_SSL_CONTEXT = _build_ssl_context()
_OPENER, _NO_REDIRECT_OPENER = _build_openers(_SSL_CONTEXT)


def _open(request, timeout: int = PAGE_TIMEOUT, follow: bool = True):
    opener = _OPENER if follow else _NO_REDIRECT_OPENER
    return opener.open(request, timeout=timeout)


def _sleep(seconds: float) -> None:
    if not STOP_REQUESTED:
        time.sleep(seconds)


def http_get(url: str, timeout: int = PAGE_TIMEOUT, retries: int = MAX_RETRIES):
    """(status, body) — 0 status means every attempt failed, never a raise."""
    last_status, last_body = 0, ""
    for attempt in range(retries):
        if STOP_REQUESTED:
            break
        try:
            with _open(urllib.request.Request(url), timeout=timeout) as response:
                raw = response.read()
                charset = response.headers.get_content_charset() or "utf-8"
                return (getattr(response, "status", 200) or 200,
                        raw.decode(charset, "replace"))
        except urllib.error.HTTPError as error:
            last_status = error.code
            try:
                last_body = error.read().decode("utf-8", "replace")
            except Exception:
                last_body = ""
            if error.code in (401, 403, 404, 410):
                return error.code, last_body
        except (OSError, urllib.error.URLError, ValueError):
            last_status = 0
        _sleep(RETRY_BACKOFF * (attempt + 1))
    return last_status, last_body


def get_json(url: str, timeout: int = LISTING_TIMEOUT):
    """(status, decoded-json-or-None) — a body that is not JSON is a verdict, not a crash."""
    status, body = http_get(url, timeout=timeout, retries=MAX_RETRIES)
    try:
        return status, json.loads(body or "null")
    except json.JSONDecodeError:
        return status, None


# ---------------------------------------------------------------------------
# Text and URL hygiene
# ---------------------------------------------------------------------------

def _unescape(text: str | None) -> str:
    return html.unescape(text or "")


def clean_text(text: str | None) -> str:
    stripped = re.sub(r"<[^>]+>", " ", _unescape(text or ""))
    return re.sub(r"\s+", " ", stripped.replace("\xa0", " ")).strip()


def _host_of(url: str) -> str:
    host = urllib.parse.urlsplit(url or "").netloc
    return host.rsplit("@", 1)[-1].split(":")[0].lower()


def _is_site_url(url: str) -> bool:
    return bool(SITE_HOST_RE.search(_host_of(url)))


def _allowed_source_url(url: str) -> bool:
    host = _host_of(url)
    return bool(host) and bool(ALLOWED_SOURCE_HOST_RE.search(host)) \
        and not TRACKER_HOST_RE.search(host)


def normalize_url(url: str, base: str = BASE_URL) -> str:
    raw = _unescape((url or "").strip())
    if not raw:
        return ""
    candidate = urllib.parse.urljoin(base, raw)
    split = urllib.parse.urlsplit(candidate)
    if split.scheme not in ("http", "https") or not split.netloc:
        return ""
    return urllib.parse.urlunsplit((split.scheme, split.netloc.lower(),
                                    split.path or "/", split.query, ""))


def embed_resource_id(url: str) -> str:
    """
    The durable id an embed host names a file by: `embed-<id>` / `emb-<id>`.

    Bounded to the path segment that carries it, so a tracking suffix cannot turn
    one source into three rows.
    """
    path = urllib.parse.urlsplit(url or "").path or ""
    match = re.search(r"/((?:embed|emb|e|v)-[A-Za-z0-9_-]{6,})", path)
    if match:
        return match.group(1)
    tail = path.strip("/").split("/")[-1]
    return re.sub(r"\.html?$", "", tail)[:80]


def service_for_host(url: str) -> str:
    host = _host_of(url)
    label = host.split(".")[-2] if host.count(".") >= 1 else host
    if not label:
        return host or "unknown"
    return re.sub(r"[^a-z0-9]+", "-", label.lower())


def scrub_brand(text: str | None) -> str:
    cleaned = BRAND_TOKEN_RE.sub(" ", _unescape(text or ""))
    cleaned = re.sub(r"\b(?:desiserials|desi\s*serials?\.watch)\b[^\w\s]?", " ",
                     cleaned, flags=re.I)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    previous = None
    while previous != cleaned:
        previous = cleaned
        cleaned = SEO_SUFFIX_RE.sub("", cleaned).strip()
    return cleaned


# ---------------------------------------------------------------------------
# Parsing: the episode title, the labeled content block, the player
# ---------------------------------------------------------------------------

def parse_episode_title(title: str | None) -> dict:
    """
    "Kaun Banega Crorepati 18 28th October 2026 Full Episode 58 Watch Online"

    -> series label, air date, episode number. All three come from the published
    string; the leading part is truncated at the date so a show whose name
    contains a number keeps it ("Bigg Boss 20").
    """
    text = clean_text(title)
    episode_match = EPISODE_RE.search(text)
    episode = int((episode_match.group("episode") or episode_match.group("episode_alt"))
                  if episode_match else 0) or None
    date_match = AIR_DATE_RE.search(text)
    air_date = None
    if date_match:
        month = {name.lower(): number for number, name in enumerate(
            ["January", "February", "March", "April", "May", "June", "July",
             "August", "September", "October", "November", "December"], start=1)}
        try:
            air_date = "%04d-%02d-%02d" % (int(date_match.group("year")),
                                          month[date_match.group("month").lower()],
                                          int(date_match.group("day")))
        except (KeyError, ValueError):
            air_date = None
    head = text[:date_match.start()].strip() if date_match else (
        text[:episode_match.start()].strip() if episode_match else text)
    head = re.sub(r"\s+(?:Full\s+Episode\s+\d+|Episode\s+\d+)\s*$", "", head,
                  flags=re.I).strip()
    season = SEASON_RE.search(text)
    return {
        "series_label": head,
        "episode": episode,
        "air_date": air_date,
        "season": int(season.group("season")) if season else None,
        "raw_title": text,
        "is_movie": bool(MOVIE_RE.search(text)),
    }


def parse_content_fields(content_html: str | None) -> dict:
    """`Serial Name:` / `Media Owner:` / `Media By:` and the boilerplate line."""
    fields: dict[str, str] = {}
    for match in FIELD_RE.finditer(content_html or ""):
        label = match.group("label").strip().lower().replace(" ", "_")
        value = clean_text(match.group("value"))
        if value and label not in fields:
            fields[label] = value
    paragraph = re.search(r"<p[^>]*>([\s\S]{20,}?)(?:<br|</p>)", content_html or "", re.I)
    return {
        "serial_name": fields.get("serial_name", ""),
        "media_owner": fields.get("media_owner", ""),
        "media_by": fields.get("media_by", ""),
        "blurb": clean_text(paragraph.group(1)) if paragraph else "",
    }


def languages_from_text(*texts: str) -> list[str]:
    """Only languages the site names: it writes them into the blurb itself."""
    found: list[str] = []
    for text in texts:
        for token, name in LANGUAGE_TOKENS.items():
            if re.search(rf"\b{token}\b", (text or ""), re.I) and name not in found:
                found.append(name)
    return found


def network_from(*texts: str) -> tuple[str | None, tuple[str | None, str | None]]:
    """(network, (country, industry)) from the publisher the site credits."""
    blob = " / ".join(t or "" for t in texts).lower()
    for key, (country, network) in NETWORK_COUNTRY.items():
        if key in blob:
            return network, (country, "television")
    return None, (None, None)


def players_from_page(page: str) -> list[dict]:
    """
    Every iframe on the rendered page that is a player, in page order.

    The allow-list is the whole defence here: the page also carries ad and
    analytics frames, and a source row naming an ad network is worse than no row.
    """
    players: list[dict] = []
    seen: set[str] = set()
    for match in IFRAME_RE.finditer(page or ""):
        url = normalize_url(match.group("src"))
        host = _host_of(url)
        if not url or not host or _is_site_url(url) or TRACKER_HOST_RE.search(host):
            continue
        path = urllib.parse.urlsplit(url).path or ""
        if not (PLAYER_HOST_RE.search(host) and PLAYER_PATH_RE.match(path)):
            continue
        if url in seen:
            continue
        seen.add(url)
        players.append({"url": url, "service": service_for_host(url),
                        "resource_id": embed_resource_id(url)})
    return players


def poster_from_embed(wp_post: dict) -> str | None:
    """`wp:featuredmedia` is present on every sampled post; keep only a real image."""
    for media in (wp_post.get("_embedded") or {}).get("wp:featuredmedia") or []:
        url = normalize_url(str(media.get("source_url") or ""))
        if url and IMAGE_EXT_RE.search(url):
            return url
    return None


def terms_from_embed(wp_post: dict) -> dict:
    """{series_slug, series_name, networks:[author names]} from `wp:term`."""
    series_slug = series_name = ""
    networks: list[str] = []
    for group in (wp_post.get("_embedded") or {}).get("wp:term") or []:
        for term in group or []:
            if not isinstance(term, dict):
                continue
            name = clean_text(term.get("name"))
            taxonomy = term.get("taxonomy")
            if taxonomy == "category" and not series_name:
                series_name = name
                series_slug = str(term.get("slug") or "")
            elif taxonomy == "post_tag":
                if name and name not in networks:
                    networks.append(name)
    for author in (wp_post.get("_embedded") or {}).get("author") or []:
        name = clean_text(author.get("name"))
        if name and name not in networks:
            networks.append(name)
    return {"series_slug": series_slug, "series_name": series_name,
            "networks": networks}


def looks_adult(*labels: str) -> int:
    return 1 if any(MATURE_TOKEN_RE.search(scrub_brand(label)) for label in labels
                    if label) else 0


# ---------------------------------------------------------------------------
# Record assembly: one episode -> one release under one series post
# ---------------------------------------------------------------------------

def series_key(series_slug: str, series_name: str) -> str:
    key = (series_slug or "").strip()
    if key:
        return key
    cleaned = re.sub(r"[^a-z0-9]+", "-", scrub_brand(series_name).lower()).strip("-")
    return cleaned or "unknown-series"


def episode_label(parsed: dict, media_type: str, season: int | None = None) -> str:
    """`S18E058` when a season is published, `E058` when it is not, else the date."""
    if media_type == "movie" or not parsed.get("episode"):
        return parsed.get("air_date") or parsed.get("raw_title") or "Episode"
    season = parsed.get("season") if season is None else season
    if season:
        return f"S{season:02d}E{parsed['episode']:03d}"
    return f"E{parsed['episode']:03d}"


def build_record(wp_post: dict, page: str, url: str) -> dict | None:
    """
    One REST record plus its rendered page -> a series post carrying ONE release.

    Returns None when the episode cannot be placed: no series term and no parseable
    title means the row has no parent to attach to, and an episode filed under a
    wrong series is worse than one left out.
    """
    terms = terms_from_embed(wp_post)
    title = _unescape((wp_post.get("title") or {}).get("rendered") or "")
    parsed = parse_episode_title(title)
    fields = parse_content_fields((wp_post.get("content") or {}).get("rendered") or "")
    series_name = terms["series_name"] or fields["serial_name"] or parsed["series_label"]
    if not series_name:
        return None
    # The category slug is the series identity when the site publishes one; with no
    # term, the label drives the key, so an episode is never filed under its own
    # 60-character page slug.
    key = terms["series_slug"] or series_key("", series_name)
    players = players_from_page(page)
    if not players:
        return None
    media_type = "movie" if parsed["is_movie"] else "series"
    # The site writes the season into the prose ("Hindi Desi Serial Kaun Banega
    # Crorepati Season 18"), not into a structured field, so the title is asked
    # first and the blurb second. A trailing bare number in a series label
    # ("Bigg Boss 20") is NOT treated as a season: it is part of the name as
    # published, and guessing it would invent a season boundary the site never
    # claimed. Where neither says "Season N", season_number stays NULL.
    season = parsed["season"]
    season_source = "title 'Season N'" if season else None
    if season is None:
        in_text = SEASON_RE.search(fields["blurb"]) or SEASON_RE.search(
            fields["serial_name"])
        season = int(in_text.group("season")) if in_text else None
        season_source = "content 'Season N'" if season else "not published"
    languages = languages_from_text(fields["blurb"], title, series_name)
    network, (country, industry) = network_from(
        " and ".join(terms["networks"]), fields["media_owner"], fields["media_by"])
    poster = poster_from_embed(wp_post) or _og_image(page)
    clean = scrub_brand(series_name)
    air_date = parsed["air_date"] or ""
    parenthetical = YEAR_PAREN_RE.search(title) or YEAR_PAREN_RE.search(series_name)
    year = int(parenthetical.group("year")) if parenthetical else None
    primary = players[0]
    # An episode is the record this site publishes, so its own facts ride on the
    # release: 3,646 episodes write one series row, and per-episode detail in
    # posts.raw_meta would be last-episode-wins.
    episode_meta = {
        "site": SITE,
        "episode_page": url,
        "post_id": wp_post.get("id"),
        "slug": wp_post.get("slug") or slug_from(url),
        "site_title": title,
        "serial_name_field": fields["serial_name"],
        "media_owner_field": fields["media_owner"],
        "media_by_field": fields["media_by"],
        "episode_claim": parsed["episode"],
        "player_count": len(players),
        "players": [{"service": p["service"], "resource_id": p["resource_id"],
                     "url": p["url"]} for p in players],
        "playability_note": ("iframe of a third-party host with no resolver in this "
                             "project; stored as catalog evidence, playable=false"),
    }
    raw_meta = {
        "site": SITE,
        "series_label_published": series_name,
        "series_label_from_title": parsed["series_label"],
        "network": network,
        "networks_published": terms["networks"],
        "season_source": season_source,
        "synopsis_source": "content blurb" if fields["blurb"] else None,
        "poster_source": ("wp:featuredmedia" if poster_from_embed(wp_post)
                         else "page og:image" if poster else None),
        "year_source": ("title parenthetical" if year
                        else "not published at series level"),
        "per_episode_data": "releases.raw_meta and releases.air_date",
    }
    episode_number = parsed["episode"]
    release = {
        "label": episode_label(parsed, media_type, season),
        "quality": None,
        "resolution": None,
        "size_bytes": None,
        "codec": None,
        "season_number": season,
        "episode_number": episode_number,
        "audio_languages": json.dumps(list(dict.fromkeys(languages)),
                                      ensure_ascii=False) if languages else None,
        "bridge_url": primary["url"],
        "origin_url": url,
        "air_date": air_date or None,
        "raw_meta": json.dumps(episode_meta, ensure_ascii=False),
        "sources": [
            {
                "source_name": f"{p['service']} embed",
                "service": p["service"],
                "resource_id": p["resource_id"],
                "source_url": p["url"],
                "final_url": None,
                "playback_type": "iframe",
                "status": DEFAULT_SOURCE_STATUS,
                "is_temporary": 0,
                "quality": None,
            }
            for p in players
        ],
    }
    return {
        "canonical_key": key,
        "title": series_name,
        "clean_title": clean or series_name,
        "year": year,
        "media_type": media_type,
        "poster_url": poster,
        "backdrop_url": None,
        "backdrop_urls": None,
        "imdb_id": None,
        "tmdb_id": None,
        "imdb_rating": None,
        "synopsis": fields["blurb"] or None,
        "genres": None,
        "director": None,
        "cast_names": None,
        "duration": None,
        "release_date": None,
        "languages": json.dumps(list(dict.fromkeys(languages)), ensure_ascii=False)
                     if languages else None,
        "country": country,
        "industry": industry,
        "seasons": None,
        "url": BASE_URL + "/category/" + (terms["series_slug"] or key) + "/",
        "slug": terms["series_slug"] or key,
        "is_18_plus": looks_adult(title, series_name, *(terms["networks"] or [])),
        "is_animated": 0,
        "media_type_verified": media_type,
        "lastmod": wp_post.get("modified") or wp_post.get("date") or air_date,
        "raw_meta": raw_meta,
        "releases": [release],
    }


def _og_image(page: str) -> str | None:
    match = OG_IMAGE_RE.search(page or "")
    url = normalize_url(match.group("url")) if match else ""
    return url if url and IMAGE_EXT_RE.search(url) else None


def slug_from(url: str) -> str:
    """
    The path segment as published, unmodified.

    This is a REST lookup key (`?slug=`), not a display string: the site's real
    slugs do end in `-watch-online`, so trimming it makes the record unfindable
    and stores a slug no query can resolve.
    """
    segment = urllib.parse.urlsplit(url or "").path.strip("/").split("/")[-1]
    return urllib.parse.unquote(segment)


def classify(post: dict) -> dict:
    return {"industry": post.get("industry") or ("television"
                                                 if post.get("media_type") == "series"
                                                 else None),
            "country": post.get("country")}


# ---------------------------------------------------------------------------
# Staging schema — the shape every per-site database in this fleet has
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
    "air_date", "raw_meta",
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
    source_site TEXT DEFAULT 'desiserials',
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
    air_date TEXT,
    raw_meta TEXT,
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
CREATE INDEX IF NOT EXISTS idx_desiserials_posts_slug ON posts(slug);
CREATE INDEX IF NOT EXISTS idx_desiserials_posts_type ON posts(media_type);
CREATE INDEX IF NOT EXISTS idx_desiserials_releases_post ON releases(post_canonical_key);
CREATE INDEX IF NOT EXISTS idx_desiserials_releases_origin ON releases(origin_url);
CREATE INDEX IF NOT EXISTS idx_desiserials_sources_status ON sources(status);
CREATE INDEX IF NOT EXISTS idx_desiserials_sources_playback ON sources(playback_type);
"""

PENDING_SELECT = (
    "SELECT loc, lastmod, slug, raw_json, scraped, error_count FROM sitemap_cache "
    "WHERE scraped IN (?, ?) ORDER BY loc;"
)


def _add_missing_columns(conn: sqlite3.Connection, table: str, wanted) -> None:
    present = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    for column in wanted:
        if column not in present:
            kind = "INTEGER" if column in INTEGER_COLUMNS else "TEXT"
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind};")


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA_TABLES)
    _add_missing_columns(conn, "posts", POST_COLUMNS)
    _add_missing_columns(conn, "releases", RELEASE_COLUMNS)
    _add_missing_columns(conn, "sources", SOURCE_COLUMNS)
    conn.executescript(_SCHEMA_INDEXES)
    conn.commit()


def _series_row(post: dict) -> dict:
    cls = classify(post)
    return {
        "canonical_key": post["canonical_key"],
        "title": post["title"],
        "clean_title": post["clean_title"],
        "year": post.get("year"),
        "media_type": post.get("media_type") if post.get("media_type")
                      in LEGAL_MEDIA_TYPES else "series",
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
        "raw_meta": json.dumps(post.get("raw_meta") or {}, ensure_ascii=False),
    }


def export_staging(db_path: Path | str = DEFAULT_DB_PATH, posts=()) -> dict:
    """
    Commits episode records into the isolated staging database.

    Additive by design: several queue records share one series row, so the post is
    merged (never overwritten wholesale), the episode's release is keyed by its own
    page URL and replaced only for that URL, and its sources follow that release.
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
            row = _series_row(post)
            placeholders = ", ".join(f":{c}" for c in POST_COLUMNS)
            # The two grade columns are sticky by MAX(), never by COALESCE: this
            # module writes one series row from 3,646 episode rows, so every later
            # clean episode would otherwise un-flag a series already marked adult.
            mergeable = [c for c in POST_COLUMNS
                         if c not in ("canonical_key", "title", "clean_title",
                                      "media_type", "source_site",
                                      "is_18_plus", "is_animated")]
            updates = ", ".join(
                f"{c} = COALESCE(excluded.{c}, posts.{c})" for c in mergeable)
            conn.execute(
                f"INSERT INTO posts ({', '.join(POST_COLUMNS)}) VALUES ({placeholders}) "
                f"ON CONFLICT(canonical_key) DO UPDATE SET "
                f"is_18_plus = MAX(posts.is_18_plus, excluded.is_18_plus), "
                f"is_animated = MAX(posts.is_animated, excluded.is_animated), "
                f"{updates};", row)
            totals["posts_written"] += 1
            for release in post.get("releases") or []:
                origin = release.get("origin_url") or row["url"]
                existing = conn.execute(
                    "SELECT id FROM releases WHERE post_canonical_key = ? "
                    "AND origin_url IS ? LIMIT 1;",
                    (row["canonical_key"], origin)).fetchone()
                values = {c: release.get(c) for c in RELEASE_COLUMNS}
                values["post_canonical_key"] = row["canonical_key"]
                values["origin_url"] = origin
                if existing:
                    release_id = existing["id"]
                    sets = ", ".join(f"{c} = ?" for c in RELEASE_COLUMNS if c
                                     != "post_canonical_key")
                    conn.execute(
                        f"UPDATE releases SET {sets} WHERE id = ?;",
                        tuple(values[c] for c in RELEASE_COLUMNS if c
                              != "post_canonical_key") + (release_id,))
                    conn.execute("DELETE FROM sources WHERE release_id = ?;",
                                 (release_id,))
                else:
                    columns = ", ".join(RELEASE_COLUMNS)
                    marks = ", ".join("?" for _ in RELEASE_COLUMNS)
                    cursor = conn.execute(
                        f"INSERT INTO releases ({columns}) VALUES ({marks});",
                        tuple(values[c] for c in RELEASE_COLUMNS))
                    release_id = cursor.lastrowid
                totals["releases_written"] += 1
                for source in release.get("sources") or []:
                    payload = {c: source.get(c) for c in SOURCE_COLUMNS}
                    payload["release_id"] = release_id
                    if payload["status"] not in ("active", "dead", "blocked",
                                                 "unverified"):
                        payload["status"] = DEFAULT_SOURCE_STATUS
                    conn.execute(
                        f"INSERT INTO sources ({', '.join(SOURCE_COLUMNS)}) "
                        f"VALUES ({', '.join(f':{c}' for c in SOURCE_COLUMNS)});",
                        payload)
                    totals["sources_written"] += 1
            conn.commit()
    finally:
        conn.close()
    return totals


# ---------------------------------------------------------------------------
# Stage one: the REST collection becomes the queue
# ---------------------------------------------------------------------------

def _queue_json(wp_post: dict) -> dict:
    """
    The projected record the crawl re-reads, kept small on purpose.

    `content.rendered` is kept because it carries `Serial Name:`/`Media Owner:`;
    `_links` and the author objects' 2 KB of `yoast_head` are not.
    """
    embedded = wp_post.get("_embedded") or {}
    return {
        "id": wp_post.get("id"), "slug": wp_post.get("slug"),
        "link": wp_post.get("link"), "title": wp_post.get("title"),
        "date": wp_post.get("date"), "modified": wp_post.get("modified"),
        "excerpt": {"rendered": clean_text((wp_post.get("excerpt") or {})
                                           .get("rendered"))},
        "content": {"rendered": (wp_post.get("content") or {}).get("rendered") or ""},
        "_embedded": {
            "wp:term": [[{"name": t.get("name"), "slug": t.get("slug"),
                          "taxonomy": t.get("taxonomy")}
                         for t in group or [] if isinstance(t, dict)]
                        for group in embedded.get("wp:term") or []],
            "author": [{"name": (a.get("name") or "")}
                       for a in embedded.get("author") or [] if isinstance(a, dict)],
            "wp:featuredmedia": [{"source_url": (m.get("source_url") or "")}
                                 for m in embedded.get("wp:featuredmedia") or []
                                 if isinstance(m, dict)],
        },
    }


def iter_catalog_posts(verbose: bool = True):
    """Pages the REST collection, bounded by MAX_PAGES and by an empty page."""
    page = 1
    while page <= MAX_PAGES:
        if STOP_REQUESTED:
            return
        url = (f"{REST_POSTS}?per_page={PAGE_SIZE}&page={page}"
               f"&orderby=modified&order=desc&_embed=1")
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
        if verbose:
            print(f"    [{SITE}] page {page}: {len(payload)} posts", flush=True)
        if not payload:
            return
        for post in payload:
            if isinstance(post, dict):
                yield post
        if len(payload) < PAGE_SIZE:
            return
        page += 1


def sync_catalog(limit: int | None = None, db_path: Path | str = DEFAULT_DB_PATH,
                 verbose: bool = True) -> int:
    """
    Queues every episode post with its projected REST record attached.

    `link` is the queue key, so the crawl's one request per episode is resumable:
    an interrupted pass leaves the rest at scraped = 0.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    records: list[tuple[str, str, str, str]] = []
    seen: set[str] = set()
    for wp_post in iter_catalog_posts(verbose=verbose):
        link = normalize_url(wp_post.get("link") or "")
        if not link or not _is_site_url(link) or link in seen:
            continue
        seen.add(link)
        records.append((link, wp_post.get("modified") or wp_post.get("date") or "",
                        wp_post.get("slug") or slug_from(link),
                        json.dumps(_queue_json(wp_post), ensure_ascii=False)))
        if limit and len(records) >= limit:
            break

    conn = sqlite3.connect(db_path, timeout=60)
    try:
        ensure_schema(conn)
        before = conn.execute("SELECT COUNT(*) FROM sitemap_cache").fetchone()[0]
        for loc, lastmod, slug, payload in records:
            conn.execute(
                """
                INSERT INTO sitemap_cache (loc, lastmod, slug, scraped, raw_json, error_count)
                VALUES (?, ?, ?, 0, ?, 0)
                ON CONFLICT(loc) DO UPDATE SET lastmod = excluded.lastmod,
                    slug = excluded.slug;
                """,
                (loc, lastmod, slug, payload),
            )
        conn.execute("UPDATE sitemap_cache SET scraped = 0 WHERE scraped = 2;")
        after = conn.execute("SELECT COUNT(*) FROM sitemap_cache").fetchone()[0]
        conn.commit()
    finally:
        conn.close()
    if verbose:
        if not records:
            print("[!] No catalog entries returned; nothing queued.", flush=True)
        else:
            print(f"[✓] [{SITE}] Queued {len(records)} episodes "
                  f"({after - before} new, {after} total).", flush=True)
    return after - before


def _bump_error(db_path: Path, loc: str, note: str, park_now: bool = False,
                requeue: bool = False) -> None:
    """Three strikes park a row; a removed page parks at once."""
    conn = sqlite3.connect(db_path, timeout=60)
    try:
        ensure_schema(conn)
        conn.execute("UPDATE sitemap_cache SET error_count = error_count + 1 "
                     "WHERE loc = ?;", (loc,))
        conn.execute(
            """UPDATE sitemap_cache SET scraped = CASE
                   WHEN ? THEN -1
                   WHEN ? THEN 2
                   WHEN error_count >= 3 THEN -1
                   ELSE scraped
               END WHERE loc = ?;""",
            (1 if park_now else 0, 1 if requeue else 0, loc))
        conn.commit()
    finally:
        conn.close()


def _parse_queue_row(loc: str, raw_json: str | None, page_html: str) -> tuple[dict | None, str]:
    if not raw_json:
        return None, "empty-queue-payload"
    try:
        wp_post = json.loads(raw_json)
    except json.JSONDecodeError:
        return None, "bad-queue-payload"
    if not isinstance(wp_post, dict):
        return None, "bad-queue-payload"
    if not (page_html or "").strip():
        return None, "empty-page"
    if "<iframe" not in page_html.lower():
        return None, "no-player-iframe"
    record = build_record(wp_post, page_html, loc)
    if record is None:
        return None, "unattributable-episode"
    return record, ""


def crawl_pending(limit: int | None = None, db_path: Path | str = DEFAULT_DB_PATH,
                  workers: int = 2, delay: float = 0.4, batch_size: int = 25,
                  verbose: bool = True) -> dict:
    """
    Fetches, parses and commits every queued episode page.

    One request per episode and no player is opened here: the embed hosts are
    third-party, iframe rows are not playable from this project, and probing them
    at 3,646 per pass buys nothing. Verification is the separate bounded `sample`.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=60)
    conn.row_factory = sqlite3.Row
    try:
        ensure_schema(conn)
        rows = conn.execute(PENDING_SELECT, QUEUED_SCRAPE_STATES).fetchall()
    finally:
        conn.close()
    if limit:
        rows = rows[:limit]
    tally = {"series": 0, "episodes": 0, "sources": 0, "declined": 0, "failed": 0}
    started = time.time()
    if verbose:
        print(f"[*] [{SITE}] {len(rows)} episodes pending "
              f"(workers={workers}, delay={delay}s).", flush=True)
    if not rows:
        return tally

    def work(row: sqlite3.Row):
        if STOP_REQUESTED:
            return None
        _sleep(delay)
        status, page = http_get(row["loc"], timeout=PAGE_TIMEOUT)
        return row, status, page

    batch: list[dict] = []
    processed = 0
    stopping = False
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [pool.submit(work, row) for row in rows]
        for future in concurrent.futures.as_completed(futures):
            outcome = future.result()
            if outcome is None:
                stopping = True
                break
            row, status, page = outcome
            processed += 1
            record, verdict = _parse_queue_row(row["loc"], row["raw_json"], page)
            if record is not None:
                batch.append(record)
                tally["episodes"] += 1
                tally["sources"] += len(record["releases"][0]["sources"])
            elif verdict == "no-player-iframe":
                tally["declined"] += 1
                _bump_error(db_path, row["loc"], verdict, requeue=status == 0)
            else:
                tally["failed"] += 1
                _bump_error(db_path, row["loc"], verdict or f"HTTP {status}",
                            park_now=status in (404, 410),
                            requeue=(status == 0
                                     and verdict != "unattributable-episode"))
            if len(batch) >= batch_size:
                _flush(db_path, batch, tally)
                batch = []
            if verbose and processed % 20 == 0:
                print(f"    ... {processed}/{len(rows)} episodes, "
                      f"{tally['sources']} sources, {int(time.time() - started)}s",
                      flush=True)
            if STOP_REQUESTED:
                stopping = True
                break
        if stopping:
            for future in futures:
                future.cancel()
    if batch:
        _flush(db_path, batch, tally)
    try:
        conn = sqlite3.connect(db_path, timeout=60)
        tally["series"] = conn.execute(
            "SELECT COUNT(*) FROM posts WHERE source_site = ?", (SITE,)).fetchone()[0]
        conn.close()
    except sqlite3.Error:
        pass
    elapsed = int(time.time() - started)
    if verbose:
        print(f"[✓] [{SITE}] series={tally['series']} episodes={tally['episodes']} "
              f"sources={tally['sources']} declined={tally['declined']} "
              f"failed={tally['failed']} in {elapsed}s", flush=True)
    return tally


def _flush(db_path: Path, batch: list[dict], totals: dict) -> None:
    written = export_staging(db_path, batch)
    conn = sqlite3.connect(db_path, timeout=60)
    try:
        ensure_schema(conn)
        for record in batch:
            conn.execute("UPDATE sitemap_cache SET scraped = 1 WHERE loc = ?;",
                         (record["raw_meta"]["episode_page"],))
        conn.commit()
    finally:
        conn.close()
    totals["releases_written"] = totals.get("releases_written", 0) + \
        written["releases_written"]


def _fetch_post_by_slug(slug: str) -> dict | None:
    status, body = http_get(f"{REST_POSTS}?slug={urllib.parse.quote(slug)}&_embed=1",
                            timeout=LISTING_TIMEOUT)
    try:
        payload = json.loads(body or "null")
    except json.JSONDecodeError:
        return None
    if status == 200 and isinstance(payload, list) and payload:
        return payload[0]
    return None


def parse_page(url: str) -> dict | None:
    """One series page, read through its REST record: the shape a reviewer asks for."""
    slug = slug_from(url)
    wp_post = _fetch_post_by_slug(slug)
    if wp_post is None:
        return None
    status, page = http_get(url, timeout=PAGE_TIMEOUT)
    if status != 200:
        return None
    return build_record(wp_post, page, url)


# ---------------------------------------------------------------------------
# Verification: one bounded sample, reported and stored honestly
# ---------------------------------------------------------------------------

def sample_verified(rows: int = 25, db_path: Path | str = DEFAULT_DB_PATH,
                    verbose: bool = True, write: bool = True) -> dict:
    """
    ONE bounded sample: `rows` embed rows, each requested once, reported.

    This does not make an iframe playable. It answers the narrower question an
    operator asks — is the durable embed still served, or has the host killed it —
    and stores `active` only when the embed document comes back containing a
    player, `blocked` when the host answers a challenge, `dead` on 404/410, and
    leaves the row `unverified` when the transport simply failed. A quota refusal
    is not a verdict about a link, so it is never written as one.
    """
    db_path = Path(db_path)
    conn = sqlite3.connect(db_path, timeout=60)
    conn.row_factory = sqlite3.Row
    report = {"requested": rows, "checked": 0, "statuses": {}, "http": {},
              "services": {}, "rows": []}
    try:
        ensure_schema(conn)
        picks = conn.execute(
            """SELECT s.id AS source_id, s.service, s.resource_id, s.source_url,
                      r.label, p.clean_title, r.post_canonical_key
               FROM sources s JOIN releases r ON r.id = s.release_id
               JOIN posts p ON p.canonical_key = r.post_canonical_key
               WHERE s.playback_type = 'iframe'
               GROUP BY r.post_canonical_key, s.service
               ORDER BY MAX(s.id) DESC;""").fetchall()
        chosen: list[sqlite3.Row] = []
        by_show: dict[str, list[sqlite3.Row]] = {}
        for pick in picks:
            by_show.setdefault(pick["post_canonical_key"], []).append(pick)
        while any(by_show.values()):
            for key in list(by_show):
                if by_show[key]:
                    chosen.append(by_show[key].pop(0))
                else:
                    del by_show[key]
            if len(chosen) >= rows:
                break
        chosen = chosen[:rows]
        for pick in chosen:
            if STOP_REQUESTED:
                break
            status, page = http_get(pick["source_url"], timeout=PAGE_TIMEOUT,
                                    retries=1)
            served_player = bool(page) and ("<iframe" in page.lower()
                                            or "player" in page.lower()
                                            or "video" in page.lower())
            just_a_moment = bool(page) and re.search(
                r"just a moment|cf-chl|challenge-platform", page, re.I) is not None
            if status in (401, 403) or just_a_moment:
                verdict_status = "blocked"
            elif status in (404, 410):
                verdict_status = "dead"
            elif status == 200 and served_player:
                verdict_status = "active"
            else:
                verdict_status = DEFAULT_SOURCE_STATUS
            report["checked"] += 1
            report["statuses"][verdict_status] = report["statuses"].get(
                verdict_status, 0) + 1
            report["http"][str(status)] = report["http"].get(str(status), 0) + 1
            report["services"][pick["service"]] = report["services"].get(
                pick["service"], 0) + 1
            line = {"post": pick["clean_title"], "label": pick["label"],
                    "service": pick["service"], "resource_id": pick["resource_id"],
                    "status": verdict_status, "http_status": status,
                    "playable": False,
                    "note": ("iframe host, no resolver in this project"
                             if verdict_status == "active" else
                             "anti-bot challenge" if verdict_status == "blocked" else "")}
            report["rows"].append(line)
            if write and verdict_status in ("active", "dead", "blocked"):
                conn.execute("UPDATE sources SET status = ?, last_checked = ? "
                             "WHERE id = ?;",
                             (verdict_status, int(time.time()), pick["source_id"]))
        if write:
            conn.commit()
    finally:
        conn.close()
    if verbose:
        print(json.dumps({k: v for k, v in report.items() if k != "rows"},
                         indent=2, ensure_ascii=False), flush=True)
        for line in report["rows"]:
            print(f"  {line['status']:<11} {str(line['http_status']):<5} "
                  f"{line['service']:<12} {line['resource_id'][:24]:24} "
                  f"{line['post'][:34]:34} {line['label']}", flush=True)
    return report


def stats(db_path: Path | str = DEFAULT_DB_PATH) -> dict:
    conn = sqlite3.connect(db_path, timeout=60)
    try:
        ensure_schema(conn)
        return {
            "site": SITE,
            "queued": conn.execute(
                "SELECT COUNT(*) FROM sitemap_cache").fetchone()[0],
            "pending": conn.execute(
                "SELECT COUNT(*) FROM sitemap_cache WHERE scraped IN (0,2)").fetchone()[0],
            "scraped": conn.execute(
                "SELECT COUNT(*) FROM sitemap_cache WHERE scraped = 1").fetchone()[0],
            "parked": conn.execute(
                "SELECT COUNT(*) FROM sitemap_cache WHERE scraped = -1").fetchone()[0],
            "posts": conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0],
            "adult_posts": conn.execute(
                "SELECT COUNT(*) FROM posts WHERE is_18_plus = 1").fetchone()[0],
            "releases": conn.execute("SELECT COUNT(*) FROM releases").fetchone()[0],
            "sources": conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0],
            "iframe_rows": conn.execute(
                "SELECT COUNT(*) FROM sources WHERE playback_type = 'iframe'").fetchone()[0],
            "services": dict(conn.execute(
                "SELECT service, COUNT(*) FROM sources GROUP BY service "
                "ORDER BY COUNT(*) DESC").fetchall()),
            "statuses": dict(conn.execute(
                "SELECT status, COUNT(*) FROM sources GROUP BY status").fetchall()),
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(f"DesiSerials staging importer "
                     f"({BASE_URL} -> {DEFAULT_DB_PATH})"))
    parser.add_argument("command", nargs="?", default="sync",
                        choices=["sync", "crawl", "parse", "sample", "stats"])
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--rows", type=int, default=25)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--delay", type=float, default=0.4)
    parser.add_argument("--batch-size", type=int, default=25, dest="batch_size")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--url", help="single episode URL for parse")
    parser.add_argument("--no-write", action="store_true", dest="no_write",
                        help="with sample: report the verdicts, store none of them")
    parser.add_argument("--quiet", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    _install_signal_handlers()
    db = Path(args.db)
    verbose = not args.quiet

    if args.command == "sync":
        sync_catalog(limit=args.limit, db_path=db, verbose=verbose)
    elif args.command == "crawl":
        crawl_pending(limit=args.limit, db_path=db, workers=args.workers,
                      delay=args.delay, batch_size=args.batch_size, verbose=verbose)
    elif args.command == "sample":
        sample_verified(rows=args.rows, db_path=db, verbose=verbose,
                        write=not args.no_write)
    elif args.command == "stats":
        print(json.dumps(stats(db), indent=2, ensure_ascii=False))
    elif args.command == "parse":
        if not args.url:
            parser.error("parse requires --url")
        record = parse_page(args.url)
        print(json.dumps(record, indent=2, ensure_ascii=False) if record
              else "null")
    return 0


if __name__ == "__main__":
    sys.exit(main())
