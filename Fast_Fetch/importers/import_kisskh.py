#!/usr/bin/env python3
"""
import_kisskh.py — isolated staging importer for https://kisskh.asia

Writes ONLY to /home/ubuntu/radd-stream-data/kisskh.db. Never touches the
production catalog; merge with Fast_Fetch/merge_catalogs.py after operator
review. Pure Python standard library. Zero pip packages.

kisskh.asia is not shaped like the other sites in this directory. It is a
WordPress install (the "cooldrama" theme) that answers its whole catalog over an
open REST API, so this importer reads JSON instead of scraping listing pages —
and the crawler needs two requests per drama at most, not one per page.

    /wp-json/wp/v2/posts?per_page=20&page=N&_embed
        the catalog itself: id, slug, link, title, dates, the synopsis
        (content.rendered), the featured image, and the site's own taxonomies
        (category / genre / country / actor / director / post_tag), resolved to
        names by _embed. 675 posts as of 2026-10-27.

    /wp-json/cooldrama/v1/player-data?post=<id>
        the media. Returns {"source": "blogger", "html": "..."} where `html` is
        a compact "blogger server data" blob whose grammar this module mirrors
        from the theme's own player.js (parsePost / detectType / parseJw /
        parseEmbed / isHiddenEpisodeMarker / readUpcomingMarker):

            [marker]<video-url>|Lang1,…,LangN|
            <track>.tl.vtt,<track>.km.vtt,… per line
            ;
            …next episode…
            {nextServer}
            …next server group (an alternate copy of the same episodes)…

        `;` separates episodes inside a group. A leading `*` marks a HIDDEN
        episode — the slot is published, the file is not (seen on episodes 16-20
        of a 20-episode drama, where the "video" is a bare host with no path). A
        leading `$` or `${…}` marks an UPCOMING one with a schedule. The blob's
        tail is usually an `<img>` poster. `{embed}` / an unrecognised shape
        means the group holds iframe pages rather than direct media.

Every episode carries the same eleven subtitle tracks (Filipino, Khmer, English,
Indonesian, Malay, Portuguese, Arabic, Hindi, German, French, Spanish), which is
the whole point of this site: original audio, subtitled. Those tracks are stored
twice on purpose — as `sources` rows with playback_type='subtitle' so they are
queryable and auditable, and as a per-episode map in `raw_meta` so a merge tool
that only understands video rows still loses nothing.

Retrieval is not neutral: the theme's player.js says it outright — *"hlscdn.vip
needs our Referer (403 without it), imostatic answers 204 with it"* — so the
per-host referer rule lives in NEEDS_REFERER_HOSTS and is what decides a probe's
verdict, rather than being rediscovered as a wave of false "dead" links.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import html as html_mod
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

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_URL = "https://kisskh.asia"
SITE = "kisskh"
REST_POSTS = f"{BASE_URL}/wp-json/wp/v2/posts"
PLAYER_DATA = f"{BASE_URL}/wp-json/cooldrama/v1/player-data"
DEFAULT_DB_PATH = Path("/home/ubuntu/radd-stream-data/kisskh.db")
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)

PAGE_SIZE = 20
# Measured from this host on 2026-10-28: per_page=100&_embed=1 answers 5.3 MB in
# 26 s and page 2 crosses the 30 s default; per_page=20&_embed=1 answers in 6 s.
# `_fields` is not an option — combined with `_embed` it returns `_embedded`
# empty, which is where the taxonomies and the poster come from.
LISTING_TIMEOUT = 60
MAX_PAGES = 200  # a paging loop that cannot terminate is worse than a short catalog
# Legacy rows some staging databases still carry a "2" for; keep accepting them.
QUEUED_SCRAPE_STATES = (0, 2)
PENDING_SELECT = (
    "SELECT loc, slug, raw_json FROM sitemap_cache"
    " WHERE scraped IN (%s) ORDER BY rowid ASC"
    % ", ".join(["?"] * len(QUEUED_SCRAPE_STATES))
)

LEGAL_MEDIA_TYPES = ("movie", "series")

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

# Host membership, label-anchored: a look-alike ("kisskh-copy.example.com") is
# not this site, and following its redirects would be following someone else.
SITE_HOST_RE = re.compile(r"(?:^|\.)kisskh\.[a-z]{2,}", re.I)

# The CDN set this site actually serves media from, observed live. A URL whose
# host is not on one of these lists is refused as a source: an ad network or a
# shortlink must never become a row a client is asked to play.
VIDEO_HOST_RE = re.compile(
    r"(?:^|\.)(?:imostatic\.[a-z]{2,}|hlscdn\.vip|cloudstorage\.naver\.com"
    r"|hugh\.cdn\.rumble\.cloud|[a-z0-9.\-]*sooplive\.com|pub-[0-9a-f]{16,}\.r2\.dev)$",
    re.I,
)
SUBTITLE_HOST_RE = re.compile(r"(?:^|\.)(?:cdnauto\.xyz|cloudinary\.com)$", re.I)
POSTER_HOST_RE = re.compile(
    r"(?:^|\.)(?:tmdb\.org|themoviedb\.org|r2\.dev|naver\.com|kisskh\.[a-z]{2,})$", re.I)
IMAGE_EXT_RE = re.compile(r"\.(?:jpg|jpeg|png|webp|gif)(?:[?#]|$)", re.I)

# Hosts that answer 403 unless the request carries an on-site Referer, and
# answer 204 when it does. The site's own default list, from player.js.
NEEDS_REFERER_HOSTS = ("hlscdn.vip",)

# Signed / object-store paths that stop working when the issuer rotates them.
# Every URL tested here has already passed the host rules below, so naming the
# bucket or the folder is enough — no anchor is needed to tell a real path from
# an ad's query string.
TEMPORARY_URL_RE = re.compile(
    r"imostatic\.[a-z]{2,}/(?:asia_live|media)/|pub-[0-9a-f]+\.r2\.dev"
    r"|/raw/upload/|X-Amz-Signature=|token=", re.I)

# Branding that must not survive into a display string. Only names this site's
# own markup uses, so no real title is eaten.
BRAND_TOKEN_RE = re.compile(r"kiss\s?kh(?:assan)?[\s\-]*\d*|cool\s?drama", re.I)

# ---------------------------------------------------------------------------
# The blob grammar, as regular expressions
# ---------------------------------------------------------------------------

INVISIBLE_RE = re.compile(r"[​-‍﻿]|\u00a0")
BRACE_ENTITY_RE = re.compile(r"&#123;|&lbrace;|&#x7b;|&#125;|&rbrace;|&#x7d;", re.I)
OPEN_BRACE_ENTITIES = ("&#123;", "&lbrace;", "&#x7b;")
# `nextserver` / `nexserver` written as bare words are the site's own typos of
# the {nextServer} separator; normalizePostText in player.js rewrites them.
BARE_SERVER_RE = re.compile(r"(^|[;\s])(?:next|nex)\s?server(?=$|[;\s])", re.I)
BARE_EMBED_RE = re.compile(r"(^|[;\s])embed(?=$|[;\s])", re.I)
DOUBLE_BRACE_RE = re.compile(r"\{\s*\{\s*(next\s*server|nex\s*server|embed)\s*\}\s*\}", re.I)
LOOSE_BRACE_RE = re.compile(r"\{\s*(next\s*server|nex\s*server|embed)\s*\}", re.I)
SERVER_SPLIT_RE = re.compile(r"\{nextServer\}", re.I)
EMBED_MARK_RE = re.compile(r"\{embed\}", re.I)
MEDIA_EXT_RE = re.compile(r"\.(?:vtt|srt|txt|m3u8|mp4|mpd)(?:[?#]|$)", re.I)
SUB_TRACK_RE = re.compile(r"/(\d+)\.([a-z]{2})\.(?:vtt|srt|txt)(?:[?#].*)?$", re.I)
# A track whose file is not named after its episode still names its language, so
# the slot can be identified by order while the track keeps its name.
LANG_ONLY_TRACK_RE = re.compile(r"\.([a-z]{2})\.(?:vtt|srt|txt)(?:[?#].*)?$", re.I)
IMG_TAG_RE = re.compile(r"""<img\b[^>]*?src=["'](?P<src>[^"']+)["'][^>]*>""", re.I)
BLOCK_TAG_RE = re.compile(r"<br\s*/?>|</?(?:p|div|li|section|article|tr|h[1-6])>", re.I)
URL_IN_TEXT_RE = re.compile(r"(?:https?:)?//\S", re.I)
UPCOMING_RE = re.compile(r"^\$(?:\{([^}]*)\})?")
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)

# The eleven subtitle codes this site publishes, and the names it puts in the
# header field, in the order they appear there.
SUBTITLE_LANGS = {
    "tl": "Filipino", "km": "Khmer", "en": "English", "id": "Indonesian",
    "ms": "Malay", "pt": "Portuguese", "ar": "Arabic", "hi": "Hindi",
    "de": "German", "fr": "French", "es": "Spanish",
}
LANG_CODE_BY_NAME = {v.lower(): k for k, v in SUBTITLE_LANGS.items()}

# Taxonomy names that decide whether a catalog entry is a film or a series.
SERIES_WORDS = ("drama", "web series", "series", "sitcom", "show", "variety")
MOVIE_WORDS = ("movie", "film")
ANIME_WORDS = ("anime", "animation", "animated")

# The site names no rating at all, so the 18+ flag is keyword-based and errs
# toward flagging: a wrongly hidden mainstream title is the cheaper mistake
# under AGENTS.md ("stored but never displayed") than a wrongly shown one.
ADULT_RE = re.compile(
    r"(?<!\d)18\s*(?:\+|plus)(?!\w)|\b(?:erotic|adult|porn(?:star)?|nude|uncensored"
    r"|softcore|hardcore|onlyfans|mms|sex)\b", re.I)

INDUSTRY_BY_COUNTRY = {
    "Korean": "K-Drama", "China": "C-Drama", "Chinese": "C-Drama",
    "Thailand": "T-Drama", "Thai": "T-Drama", "Japan": "J-Drama", "Japanese": "J-Drama",
}

# ---------------------------------------------------------------------------
# HTTP layer
# ---------------------------------------------------------------------------


def _build_ssl_context() -> ssl.SSLContext:
    """Certificate checking is never disabled here; a CDN with a bad chain is
    recorded as `error`, not silently trusted."""
    return ssl.create_default_context()


class _StopRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _build_openers(context: ssl.SSLContext):
    """Returns (following, non-following) openers built on this SSL context."""
    following = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=context))
    following.addheaders = [
        ("User-Agent", USER_AGENT),
        ("Accept", "application/json,text/html;q=0.9,*/*;q=0.8"),
        ("Accept-Language", "en-US,en;q=0.9"),
    ]
    non_following = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=context), _StopRedirect())
    non_following.addheaders = [("User-Agent", USER_AGENT)]
    return following, non_following


_SSL_CONTEXT = _build_ssl_context()
_OPENER, _NO_REDIRECT_OPENER = _build_openers(_SSL_CONTEXT)


def http_get(url: str, timeout: int = 30, retries: int = 3):
    """Returns (status_code, final_url, body), following redirects. Never raises."""
    last_status, last_url, last_body = 0, url, ""
    for attempt in range(1, retries + 1):
        try:
            resp = _OPENER.open(url, timeout=timeout)
            body = resp.read().decode("utf-8", "replace")
            return getattr(resp, "status", 200) or 200, resp.geturl(), body
        except urllib.error.HTTPError as exc:
            last_status = exc.code
            try:
                last_body = exc.read().decode("utf-8", "replace")
            except Exception as exc2:
                last_body = f"[unreadable error body] {exc2}"
            if exc.code in (401, 403, 404, 410):
                return exc.code, url, last_body  # final — retrying a gate is rude
        except Exception as exc:
            last_status, last_body = 0, f"[network error] {exc}"
        if attempt < retries:
            time.sleep(min(2 ** attempt, 8))
    return last_status, last_url, last_body


def http_get_once(url: str, referer: str | None = None, timeout: int = 25):
    """One request, redirects left alone: returns (status, location, body)."""
    headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if referer:
        headers["Referer"] = referer
    try:
        resp = _NO_REDIRECT_OPENER.open(
            urllib.request.Request(url, headers=headers), timeout=timeout)
        body = resp.read().decode("utf-8", "replace")
        status = getattr(resp, "status", 200) or 200
    except urllib.error.HTTPError as exc:
        status = exc.code
        try:
            body = exc.read().decode("utf-8", "replace")
        except Exception as exc2:
            body = f"[unreadable error body] {exc2}"
        resp = exc
    except Exception as exc:
        return 0, None, f"[network error] {exc}"
    location = None
    try:
        location = resp.headers.get("Location")
    except AttributeError:
        pass
    return status, location, body


def get_json(url: str, timeout: int = 30):
    """(status, parsed_json_or_none). A JSON error object parses but is not a list."""
    status, _, body = http_get(url, timeout=timeout)
    if status != 200:
        return status, None
    try:
        return 200, json.loads(body)
    except (json.JSONDecodeError, TypeError) as exc:
        print(f"[!] [{SITE}] {url} is not JSON: {exc}", flush=True)
        return status, None


# ---------------------------------------------------------------------------
# Small text / URL helpers
# ---------------------------------------------------------------------------


def _unescape(text: str | None) -> str:
    return html_mod.unescape(html_mod.unescape(text or ""))


def _clean_text(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", _unescape(re.sub(r"<[^>]+>", " ", text))).strip()


def _scrub_invisible(text: str | None) -> str:
    """Zero-width and NBSP characters are how a blob hides a marker from a regex."""
    return INVISIBLE_RE.sub(" ", text or "").strip()


def _host_of(url: str) -> str:
    return urllib.parse.urlsplit(url or "").netloc.lower().replace("www.", "")


def _is_site_url(url: str) -> bool:
    return bool(SITE_HOST_RE.search(_host_of(url)))


def _normalize_http_url(url: str, base: str = BASE_URL) -> str:
    """Protocol-relative becomes absolute; anything not http(s) is refused."""
    value = _scrub_invisible(url)
    if not value:
        return ""
    if value.startswith("//"):
        value = urllib.parse.urlsplit(base).scheme + ":" + value
    try:
        parts = urllib.parse.urlsplit(value)
    except ValueError:
        return ""
    if parts.scheme not in ("http", "https"):
        return ""
    if not parts.netloc:
        return ""
    return value


def _media_kind(url: str) -> str | None:
    """
    'video' | 'subtitle' | 'bridge' | 'embed' | 'poster' | None.
    None means the host is not one this site serves media from, so the URL is not
    ours to store — an ad network or a shortlink must never become a source row.
    'bridge' is a real media host with no file behind it (a hidden episode slot).
    """
    host = _host_of(url)
    path = urllib.parse.urlsplit(url or "").path.lower()
    if not host:
        return None
    if SUBTITLE_HOST_RE.search(host):
        return "subtitle"
    if VIDEO_HOST_RE.search(host):
        return "video" if re.search(r"\.(mp4|m3u8|mpd)(?:[?#]|$)", path) else "bridge"
    if POSTER_HOST_RE.search(host) and IMAGE_EXT_RE.search(path):
        return "poster"
    if SITE_HOST_RE.search(host):
        return "embed"
    return None


def _resource_id(url: str) -> str:
    """
    The last path segment minus its file extension — the CDN's own handle. A
    manifest is named after its folder, so the folder carries the id.
    """
    segments = [s for s in urllib.parse.urlsplit(url or "").path.split("/") if s]
    if not segments:
        return ""
    name = segments[-1].rsplit(".", 1)[0] if "." in segments[-1] else segments[-1]
    if name == "manifest" and len(segments) > 1:
        parent = segments[-2]
        return parent.rsplit(".", 1)[0] if "." in parent else parent
    return name


def _is_temporary(url: str) -> int:
    return 1 if TEMPORARY_URL_RE.search(url or "") else 0


def needs_referrer(url: str, hosts=NEEDS_REFERER_HOSTS) -> bool:
    """True when this host answers 403 without an on-site Referer."""
    host = _host_of(url)
    return any(host == h or host.endswith("." + h) for h in hosts)


def _name_list(names) -> str | None:
    """Comma-joined, deduplicated, provenance-clean; None when nothing survives."""
    out: list[str] = []
    for raw in names or ():
        name = scrub_brand(_clean_text(raw))
        if name and name.lower() not in {o.lower() for o in out}:
            out.append(name)
    return ", ".join(out) if out else None


def scrub_brand(text: str | None) -> str:
    """Removes site branding from a display string; URLs are never passed here."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", BRAND_TOKEN_RE.sub(" ", text)).strip(" -–:,,|&")


# ---------------------------------------------------------------------------
# The blogger-server-data blob
# ---------------------------------------------------------------------------


def _brace_entity(match) -> str:
    return "{" if match.group(0).lower() in OPEN_BRACE_ENTITIES else "}"


def _canonical_marker(match) -> str:
    """`{{ nex  Server }}` and `{ EMBED }` both collapse to the canonical spelling."""
    word = match.group(1).lower().replace(" ", "")
    return "{nextServer}" if "server" in word else "{embed}"


def normalize_blob(text: str | None) -> str:
    """
    The theme's normalizePostText, in Python: entities, invisible characters and
    the site's own misspellings become the canonical {nextServer} / {embed}
    markers, so one parser sees what the player would have played.
    """
    out = _scrub_invisible(text or "")
    out = BRACE_ENTITY_RE.sub(_brace_entity, out)
    # A separator inside an HTML comment is markup the player never rendered: it
    # must not split the blob into groups.
    out = HTML_COMMENT_RE.sub(" ", out)
    out = re.sub(r"\r\n?", "\n", out)
    out = DOUBLE_BRACE_RE.sub(_canonical_marker, out)
    out = LOOSE_BRACE_RE.sub(_canonical_marker, out)
    out = BARE_SERVER_RE.sub(lambda m: f"{m.group(1)}{{nextServer}}", out)
    out = BARE_EMBED_RE.sub(lambda m: f"{m.group(1)}{{embed}}", out)
    return out


def split_html_and_poster(text: str) -> tuple[str, str]:
    """Pulls the trailing `<img>` poster out of the blob and returns (poster, rest)."""
    m = IMG_TAG_RE.search(text or "")
    poster = _normalize_http_url(_unescape(m.group("src"))) if m else ""
    rest = IMG_TAG_RE.sub(" ", text or "")
    return poster, rest


def strip_html_to_lines(text: str) -> list[str]:
    """Block tags in either direction end a line; scripts, styles and comments vanish."""
    out = HTML_COMMENT_RE.sub(" ", text or "")
    out = re.sub(r"<(?:script|style)\b.*?</(?:script|style)>", " ", out, flags=re.S | re.I)
    out = BLOCK_TAG_RE.sub("\n", out)
    out = re.sub(r"<[^>]*>", " ", out)
    return [line for line in (_scrub_invisible(l) for l in out.split("\n")) if line]


def split_server_groups(text: str) -> list[dict]:
    """
    Splits on {nextServer} and types each group. A group is 'jw' (direct media +
    a subtitle list) when it holds a `|` header or a media file URL, otherwise it
    is 'embed' (iframe pages). A group holding no URL at all is the site's own
    stray separator, and the player would have nothing to render from it.
    Mirrors detectType() in player.js.
    """
    groups: list[dict] = []
    for raw in SERVER_SPLIT_RE.split(normalize_blob(text)):
        body = raw.strip()
        if not body:
            continue
        forced = bool(EMBED_MARK_RE.search(body))
        body = EMBED_MARK_RE.sub("\n", body).strip()
        if not body or not URL_IN_TEXT_RE.search(body):
            continue
        groups.append({"type": "embed" if forced else detect_type(body), "body": body})
    return groups


def detect_type(text: str) -> str:
    return "jw" if ("|" in text or MEDIA_EXT_RE.search(text)) else "embed"


def _split_head_fields(line: str) -> list[str]:
    """
    splitJwFields(): `|` separates fields, but not inside a `${…}` countdown, so a
    scheduled-release expression survives whole.
    """
    fields: list[str] = []
    field = ""
    in_countdown = False
    for i, ch in enumerate(line):
        if ch == "$" and line[i + 1:i + 2] == "{":
            in_countdown = True
        elif ch == "}":
            in_countdown = False
        if ch == "|" and not in_countdown:
            fields.append(field.strip())
            field = ""
        else:
            field += ch
    fields.append(field.strip())
    return fields


def read_markers(line: str) -> dict:
    """`*` = hidden slot, `$` / `${…}` = scheduled slot."""
    text = _scrub_invisible(line)
    hidden = text.startswith("*")
    if hidden:
        text = text[1:]
    upcoming = None
    m = UPCOMING_RE.match(text)
    if m:
        upcoming = (m.group(1) or "").strip()
        text = text[m.end():]
    return {"hidden": hidden, "upcoming": upcoming, "text": text.strip()}


def episode_from_track_url(url: str) -> tuple[int | None, str | None]:
    """
    `…/16.ms.vtt` → (16, 'ms'). The filename is the only episode id the blob
    carries; when a track is not named after its episode the language still is,
    so the caller keeps the name and falls back to slot order for the number.
    """
    m = SUB_TRACK_RE.search(url or "")
    if m:
        return int(m.group(1)), m.group(2)
    m = LANG_ONLY_TRACK_RE.search(url or "")
    if m:
        return None, m.group(1)
    return None, None


def subtitle_name(code: str | None) -> str:
    if not code:
        return ""
    return SUBTITLE_LANGS.get(code.lower(), code.upper())


def parse_jw_group(body: str) -> list[dict]:
    """One dict per episode slot: {episode, videos, subtitles, hidden, upcoming}."""
    episodes: list[dict] = []
    for block in body.split(";"):
        parsed = parse_jw_block(block)
        if parsed:
            episodes.append(parsed)
    return episodes


def parse_jw_block(block: str) -> dict | None:
    lines = strip_html_to_lines(block)
    if not lines:
        return None
    head = read_markers(lines[0])
    fields = _split_head_fields(head["text"])
    url = _normalize_http_url(fields[0]) if fields else ""
    langs = [l.strip() for l in fields[1].split(",") if l.strip()] if len(fields) > 1 else []
    subtitles: dict[str, str] = {}
    episode: int | None = None
    for line in lines[1:]:
        for candidate in (c.strip().rstrip(",;") for c in line.split(",")):
            track = _normalize_http_url(candidate)
            if not track:
                continue
            number, code = episode_from_track_url(track)
            if number is not None and episode is None:
                episode = number
            name = subtitle_name(code)
            if name:
                subtitles[name] = track
    if not url and not subtitles:
        return None
    return {"episode": episode, "video": url, "subtitle_languages": langs,
            "subtitles": subtitles, "hidden": head["hidden"],
            "scheduled": head["upcoming"]}


def parse_embed_group(body: str) -> list[dict]:
    """An embed group lists iframe pages, one per episode, no subtitle header."""
    episodes: list[dict] = []
    for token in re.split(r"[;\n]+", body):
        marker = read_markers(token)
        url = _normalize_http_url(marker["text"].rstrip(",;"))
        if not url or MEDIA_EXT_RE.search(url):
            continue
        number, _code = episode_from_track_url(url)
        episodes.append({"episode": number, "video": "", "embed": url,
                         "subtitle_languages": [], "subtitles": {},
                         "hidden": marker["hidden"], "scheduled": marker["upcoming"]})
    return episodes


def merge_episode_groups(groups: list[dict]) -> dict:
    """
    Collapses server groups onto one row per episode: the same episode printed on
    three servers is three sources for one release, not three releases. Episode
    numbers fall back to slot order when a blob carries no subtitle filename.
    """
    episodes: dict[int, dict] = {}
    for index, group in enumerate(groups, start=1):
        items = parse_jw_group(group["body"]) if group["type"] == "jw" \
            else parse_embed_group(group["body"])
        for slot, item in enumerate(items, start=1):
            number = item["episode"] or slot
            row = episodes.setdefault(number, {
                "episode": number, "servers": [], "subtitles": {},
                "subtitle_languages": [], "hidden": True, "scheduled": None})
            if item["video"] or item.get("embed"):
                row["servers"].append({
                    "server_index": index, "kind": group["type"],
                    "url": item["video"] or item["embed"],
                    "hidden": item["hidden"], "scheduled": item["scheduled"]})
            row["hidden"] = row["hidden"] and item["hidden"]
            row["scheduled"] = row["scheduled"] or item["scheduled"]
            for name, track in item["subtitles"].items():
                row["subtitles"].setdefault(name, track)
            for lang in item["subtitle_languages"]:
                if lang not in row["subtitle_languages"]:
                    row["subtitle_languages"].append(lang)
    return {n: episodes[n] for n in sorted(episodes)}


# ---------------------------------------------------------------------------
# The catalog record
# ---------------------------------------------------------------------------


def terms_from_embed(wp_post: dict) -> dict[str, list[str]]:
    """_embedded["wp:term"] → {"genre": [...], "country": [...], ...}, names deduped."""
    terms: dict[str, list[str]] = {}
    for group in (wp_post.get("_embedded") or {}).get("wp:term") or []:
        for term in group:
            tax = (term.get("taxonomy") or "term").lower()
            name = _clean_text(term.get("name"))
            if not name:
                continue
            bucket = terms.setdefault(tax, [])
            if name.lower() not in {b.lower() for b in bucket}:
                bucket.append(name)
    return terms


def poster_from_embed(wp_post: dict) -> str:
    """The featured image, if it is on an image host. A broken link is not a poster."""
    for media in (wp_post.get("_embedded") or {}).get("wp:featuredmedia") or []:
        url = _normalize_http_url(media.get("source_url") or "")
        if url and _media_kind(url) == "poster":
            return url
    return ""


def plain_text(html_body: str | None) -> str:
    return re.sub(r"\s+", " ", _unescape(re.sub(r"<[^>]+>", " ", html_body or ""))).strip()


def media_type_for(terms: dict[str, list[str]], episode_count: int) -> str:
    """The site's own shelf decides; an unknown shelf falls back to the episode count."""
    names = {n.lower() for group in terms.values() for n in group}
    if names & set(MOVIE_WORDS):
        return "movie"
    if names & set(SERIES_WORDS):
        return "series"
    return "series" if episode_count > 1 else "movie"


def looks_animated(terms: dict[str, list[str]], title: str) -> int:
    joined = " ".join([title] + [n for group in terms.values() for n in group]).lower()
    return 1 if any(w in joined for w in ANIME_WORDS) else 0


def is_adult(terms: dict[str, list[str]], title: str) -> int:
    """
    Keyword-based, because kisskh publishes no rating field. Only the site's own
    labels count — never the synopsis, because a blurb that mentions sex is not a
    genre, and hiding a mainstream title is the more expensive mistake to make in
    the other direction.
    """
    labels = " ".join([title] + [n for group in terms.values() for n in group])
    return 1 if ADULT_RE.search(labels) else 0


def subtitle_language_names(episodes: dict) -> list[str]:
    names: list[str] = []
    for row in episodes.values():
        for name in row["subtitles"]:
            if name not in names:
                names.append(name)
    return names


def build_post(wp_post: dict, player: dict | None) -> dict | None:
    """
    Turns one REST record (plus its player-data, if fetched) into a staging post.
    Pure: no network, no clock, no database.
    """
    post_id = wp_post.get("id")
    link = _normalize_http_url(wp_post.get("link") or "")
    slug = _scrub_invisible(wp_post.get("slug") or "")
    if not isinstance(post_id, (int, str)) or not link or not slug:
        return None
    title = _clean_text((wp_post.get("title") or {}).get("rendered"))
    clean = scrub_brand(title)
    if not clean:
        return None
    terms = terms_from_embed(wp_post)
    blob = (player or {}).get("html") or ""
    blob_poster, blob_rest = split_html_and_poster(blob)
    groups = split_server_groups(blob_rest)
    episodes = merge_episode_groups(groups)
    synopsis = plain_text((wp_post.get("content") or {}).get("rendered")) or None
    genre_names = (terms.get("genre") or []) + (terms.get("post_tag") or []) \
        + (terms.get("category") or [])
    countries = terms.get("country") or []
    sub_names = subtitle_language_names(episodes)
    media_type = media_type_for(terms, len(episodes))
    return {
        "id": post_id, "canonical_key": slug, "title": title, "clean_title": clean,
        "year": None, "media_type": media_type,
        "poster_url": poster_from_embed(wp_post) or blob_poster or None,
        "tmdb_id": None, "imdb_id": None, "imdb_rating": None,
        "synopsis": _meaningful(synopsis), "genres": _name_list(genre_names),
        "director": _name_list(terms.get("director")),
        "cast_names": _name_list(terms.get("actor")),
        "duration": None,
        "release_date": (wp_post.get("date") or "")[:10] or None,
        "languages": _name_list(sub_names), "country": _name_list(countries),
        "seasons": None, "url": link, "slug": slug,
        "is_18_plus": is_adult(terms, title), "is_animated": looks_animated(terms, title),
        "source_site": SITE, "lastmod": wp_post.get("modified"),
        "episodes": episodes,
        "releases": releases_for(wp_post, episodes, media_type),
        "raw_meta": {
            "wp_post_id": post_id, "link": link, "terms": terms,
            "player_source": (player or {}).get("source"),
            "player_updated": (player or {}).get("updated"),
            "blog_id": (player or {}).get("blogId"),
            "blob_poster": blob_poster or None,
            "site_media_id": _clean_text((player or {}).get("title")) or None,
            "subtitle_languages": sub_names,
            "episodes": [
                {"episode": row["episode"], "hidden": row["hidden"],
                 "scheduled": row["scheduled"],
                 "servers": [{"server_index": s["server_index"], "kind": s["kind"],
                              "url": s["url"]} for s in row["servers"]],
                 "subtitles": row["subtitles"]}
                for row in episodes.values()],
        },
    }


def _meaningful(text: str | None) -> str | None:
    """The site's own placeholders ('', 'N/A', 'None', '-') must not read as data."""
    if not text:
        return None
    stripped = text.strip()
    if not stripped or stripped.lower() in ("n/a", "na", "none", "null", "-", "unknown"):
        return None
    if re.fullmatch(r"[\s.,:;|·–—-]+", stripped):
        return None
    return stripped


def releases_for(wp_post: dict, episodes: dict, media_type: str = "series") -> list[dict]:
    """
    One release per episode slot. The label is display text, so it says nothing
    about the site. The blob's header field names the *subtitle* languages, not
    the audio ones, so audio_languages stays NULL rather than claiming a dub the
    file does not have — the language set lives in posts.languages and in one
    subtitle source row per track.
    """
    releases: list[dict] = []
    for number, row in episodes.items():
        servers = row["servers"]
        if not servers:
            continue
        solo = media_type == "movie" and len(episodes) == 1
        label = "Full Movie" if solo else f"Episode {number}"
        releases.append({
            "label": label,
            "quality": None, "resolution": None, "size_bytes": None, "codec": None,
            "season_number": None, "episode_number": number,
            "audio_languages": None,
            "bridge_url": servers[0]["url"],
            "sources": sources_for(row),
        })
    return releases


def sources_for(row: dict) -> list[dict]:
    """Video sources first (honest status per server), then one row per subtitle track."""
    out: list[dict] = []
    for server in row["servers"]:
        url = server["url"]
        kind = _media_kind(url)
        if kind not in ("video", "bridge", "embed"):
            continue
        playable = kind == "video"
        if server["hidden"]:
            status = "blocked"          # the slot is published; the file is not
        elif playable:
            status = "unverified"       # nothing has asked this URL anything yet
        else:
            status = "js_required"      # a page, not an object: nothing to play directly
        out.append({
            "source_name": f"Server {server['server_index']}",
            "service": _host_of(url), "resource_id": _resource_id(url),
            "source_url": url, "final_url": url,
            "playback_type": "stream" if playable else "iframe",
            "status": status,
            "is_temporary": _is_temporary(url),
            "quality": None, "last_checked": None,
        })
    for name, url in sorted(row["subtitles"].items()):
        if _media_kind(url) != "subtitle":
            continue
        out.append({
            "source_name": name, "service": _host_of(url),
            "resource_id": _resource_id(url), "source_url": url, "final_url": url,
            "playback_type": "subtitle",
            # `active` is a claim about an answer we have not received: a crawl
            # without --probe never asks the track host anything. The track is
            # recorded as unverified until a probe says otherwise.
            "status": "unverified",
            "is_temporary": _is_temporary(url),
            "quality": None, "last_checked": None,
        })
    return out


def classify(post: dict) -> dict:
    """Derived columns the site states but does not store as fields."""
    country = (post.get("country") or "").split(",")[0].strip()
    return {
        "country": country or None,
        "industry": INDUSTRY_BY_COUNTRY.get(country),
        "languages": post.get("languages"),
        "media_type": post.get("media_type") or "series",
    }


# ---------------------------------------------------------------------------
# Link resolution (opt-in; the blob already carries playable objects)
# ---------------------------------------------------------------------------


def probe_source(url: str, referer: str | None = None) -> dict:
    """One request, no redirect chain spent: the answer IS the status/Location."""
    status, location, _body = http_get_once(url, referer=referer)
    verdict = {
        200: "active", 206: "active", 302: "active", 301: "active",
        204: "blocked", 401: "blocked", 403: "blocked", 404: "dead",
        410: "dead", 429: "unknown", 0: "error",
    }.get(status, "unknown")
    return {"status_code": status, "status": verdict, "location": location,
            "checked_with_referer": bool(referer)}


def resolve_links(post: dict, probe: bool = False, deep: bool = False) -> dict:
    """
    Without --probe this only labels what the blob already says: which sources
    need the site's Referer, and which objects are signed and will expire. Every
    row keeps the status the blob can support — `unverified` for a URL nobody has
    asked, `blocked` for a slot published with no file, `js_required` for a page.

    --probe asks each source row once, with the per-host referer rule applied, and
    writes the answer into `status`. That includes every subtitle track, because
    a track the viewer depends on is exactly the row worth checking. It costs one
    request per row — a drama with twelve episodes has twelve videos and 132
    tracks — and the CDNs rate-limit, so it stays opt-in.
    """
    checked = int(time.time())
    for rel in post.get("releases") or []:
        for src in rel.get("sources") or []:
            url = src.get("source_url") or ""
            src["needs_referer"] = needs_referrer(url)
            if not probe:
                continue
            referer = BASE_URL + (post.get("url") or "/") if src["needs_referer"] else None
            verdict = probe_source(url, referer=referer)
            src["status"] = verdict["status"]
            src["last_checked"] = checked
            if verdict["location"] and deep:
                src["final_url"] = _normalize_http_url(verdict["location"], base=url)
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

# The two child tables' columns, named once so the INSERT and the migration guard
# below cannot drift apart from the CREATE TABLE above.
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
    source_site TEXT DEFAULT 'kisskh',
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
    playback_type TEXT DEFAULT 'url',
    status TEXT DEFAULT 'active',
    is_temporary INTEGER DEFAULT 0,
    quality TEXT,
    last_checked INTEGER,
    FOREIGN KEY (release_id) REFERENCES releases(id)
);

"""

# Indexes are created after the migration below, or a database that predates the
# column they sit on fails to open rather than being upgraded.
_SCHEMA_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_kisskh_posts_slug ON posts(slug);
CREATE INDEX IF NOT EXISTS idx_kisskh_posts_country ON posts(country);
CREATE INDEX IF NOT EXISTS idx_kisskh_sources_status ON sources(status);
CREATE INDEX IF NOT EXISTS idx_kisskh_sources_playback ON sources(playback_type);
CREATE INDEX IF NOT EXISTS idx_kisskh_releases_post ON releases(post_canonical_key);
"""


def _add_missing_columns(conn: sqlite3.Connection, table: str, wanted) -> None:
    have = {c[1] for c in conn.execute(f"PRAGMA table_info({table});").fetchall()}
    for col in wanted:
        if col in have:
            continue
        # The declared type travels with the column: an INTEGER stored under TEXT
        # affinity comes back as a string, and `last_checked > x` becomes a
        # comparison of digits rather than of times.
        decl = "INTEGER" if col in INTEGER_COLUMNS else "TEXT"
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl};")


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Creates the staging shape; ALTERs only for a column the guard finds missing."""
    conn.executescript(_SCHEMA_TABLES)
    _add_missing_columns(conn, "posts", POST_COLUMNS + ("scraped_at",))
    _add_missing_columns(conn, "releases", RELEASE_COLUMNS)
    _add_missing_columns(conn, "sources", SOURCE_COLUMNS)
    conn.executescript(_SCHEMA_INDEXES)


def export_staging(db_path: Path | str = DEFAULT_DB_PATH, posts=()) -> dict:
    """
    Commits parsed post dicts into the isolated staging database.

    Idempotent: a re-scraped drama refreshes its own post row and replaces only
    the releases that drama's own blob produced, so a resumed crawl never
    deletes another title's prints.
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
            raw_meta = post.get("raw_meta")
            if not isinstance(raw_meta, str):
                raw_meta = json.dumps(raw_meta or {}, ensure_ascii=False)
            row = {
                "canonical_key": post["canonical_key"],
                "title": post.get("title") or post["clean_title"],
                "clean_title": post["clean_title"],
                "year": post.get("year"),
                "media_type": post.get("media_type") or "series",
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
                "raw_meta": raw_meta,
            }
            placeholders = ", ".join(f":{c}" for c in POST_COLUMNS)
            updates = ", ".join(
                f"{c} = COALESCE(excluded.{c}, posts.{c})"
                for c in POST_COLUMNS
                if c not in ("canonical_key", "title", "clean_title", "media_type",
                             "url", "slug", "source_site", "raw_meta", "year")
            )
            conn.execute(
                f"""
                INSERT INTO posts ({", ".join(POST_COLUMNS)}) VALUES ({placeholders})
                ON CONFLICT(canonical_key) DO UPDATE SET
                    title = excluded.title,
                    clean_title = excluded.clean_title,
                    media_type = excluded.media_type,
                    url = excluded.url,
                    slug = excluded.slug,
                    source_site = excluded.source_site,
                    raw_meta = excluded.raw_meta,
                    year = COALESCE(excluded.year, posts.year),
                    is_18_plus = MAX(posts.is_18_plus, excluded.is_18_plus),
                    is_animated = MAX(posts.is_animated, excluded.is_animated),
                    {updates},
                    scraped_at = CURRENT_TIMESTAMP;
                """,
                row,
            )
            totals["posts_written"] += 1

            page_url = row["url"]
            stale = [r["id"] for r in conn.execute(
                "SELECT id FROM releases WHERE post_canonical_key = ?"
                " AND (origin_url = ? OR origin_url IS NULL)",
                (post["canonical_key"], page_url)).fetchall()]
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
                for src in rel.get("sources") or []:
                    conn.execute(
                        f"INSERT INTO sources ({', '.join(SOURCE_COLUMNS)})"
                        f" VALUES ({', '.join('?' * len(SOURCE_COLUMNS))});",
                        (cur.lastrowid, src.get("source_name"), src.get("service"),
                         src.get("resource_id"), src.get("source_url"),
                         src.get("final_url") or src.get("source_url"),
                         src.get("playback_type", "url"), src.get("status", "active"),
                         int(src.get("is_temporary") or 0),
                         src.get("quality") or rel.get("quality"),
                         src.get("last_checked")),
                    )
                    totals["sources_written"] += 1

            if page_url:
                conn.execute(
                    """
                    INSERT INTO sitemap_cache (loc, lastmod, slug, scraped, raw_json, error_count)
                    VALUES (?, ?, ?, 1, ?, 0)
                    ON CONFLICT(loc) DO UPDATE SET scraped = 1, slug = excluded.slug,
                        lastmod = excluded.lastmod, raw_json = excluded.raw_json;
                    """,
                    (page_url, post.get("lastmod"), row["slug"], raw_meta),
                )
        conn.commit()
    finally:
        conn.close()
    return totals


# ---------------------------------------------------------------------------
# Queue and crawl
# ---------------------------------------------------------------------------


def _queue_json(wp_post: dict) -> dict:
    """The smallest record that lets the crawl run without re-fetching the REST row."""
    return {
        "id": wp_post.get("id"), "slug": wp_post.get("slug"),
        "link": wp_post.get("link"), "title": wp_post.get("title"),
        "date": wp_post.get("date"), "modified": wp_post.get("modified"),
        "content": wp_post.get("content"), "_embedded": wp_post.get("_embedded"),
    }


def iter_catalog_posts():
    """
    Pages the WP REST collection, bounded by MAX_PAGES. Stops on a short page, an
    empty page, a JSON error object or a non-200 — whichever comes first — so a
    shrunken catalog cannot spin forever.
    """
    page = 1
    while page <= MAX_PAGES:
        url = f"{REST_POSTS}?per_page={PAGE_SIZE}&page={page}&_embed=1&orderby=id&order=asc"
        status, payload = get_json(url, timeout=LISTING_TIMEOUT)
        if status != 200:
            print(f"[!] [{SITE}] page {page} -> HTTP {status}", flush=True)
            return
        if not isinstance(payload, list):
            print(f"[!] [{SITE}] page {page} is not a post list: {payload}", flush=True)
            return
        if not payload:
            return
        for wp_post in payload:
            yield wp_post
        if len(payload) < PAGE_SIZE:
            return
        page += 1


def sync_catalog(limit: int | None = None, db_path: Path | str = DEFAULT_DB_PATH,
                 verbose: bool = True) -> int:
    """
    Queues every catalog entry into sitemap_cache, carrying the REST record with
    it so the crawl needs only the player-data call per drama.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    records: list[tuple[str, str, str, str]] = []
    seen: set[str] = set()
    for wp_post in iter_catalog_posts():
        link = _normalize_http_url(wp_post.get("link") or "")
        if not link or not _is_site_url(link) or link in seen:
            continue
        seen.add(link)
        records.append((link, wp_post.get("modified") or "", wp_post.get("slug") or "",
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
            print(f"[✓] [{SITE}] Queued {len(records)} dramas "
                  f"({after - before} new, {after} total).", flush=True)
    return after - before


def _fetch_post_by_slug(slug: str) -> dict | None:
    """
    Recovery path for a queue row that predates the embedded record.

    `slug` is the slug as the site stores it, not as a URL spells it: this is the
    one place that percent-encodes, so callers must hand it a decoded value.
    """
    url = f"{REST_POSTS}?slug={urllib.parse.quote(slug or '')}&_embed=1"
    status, payload = get_json(url)
    if isinstance(payload, list) and payload:
        return payload[0]
    return None


def fetch_player_blob(post_id) -> tuple[int, dict | None]:
    """
    (status, the answer that carries a media blob) for one drama.

    A JSON answer with no `html` is the site saying it has published nothing for
    this drama yet; a non-200 is a transport or gate answer, and the two have to
    be told apart before deciding what the queue entry is worth.
    """
    status, payload = get_json(f"{PLAYER_DATA}?post={post_id}")
    if isinstance(payload, dict) and (payload.get("html") or "").strip():
        return status, payload
    return status, None


def _parse_record(loc: str, raw_json: str | None, slug: str):
    """
    Returns (post, verdict). `verdict` names *why* a drama was declined, so the
    driver can park a gone entry on the first sighting instead of spending three
    retries on a decision the site has already made.
    """
    wp_post = None
    if raw_json:
        try:
            wp_post = json.loads(raw_json)
        except json.JSONDecodeError:
            wp_post = None
    if not isinstance(wp_post, dict) or "id" not in wp_post:
        wp_post = _fetch_post_by_slug(slug)
        if wp_post is None:
            return None, "not-a-post"
    status, player = fetch_player_blob(wp_post["id"])
    if player is None:
        if status in (401, 403, 404, 410):
            return None, "removed"      # the site no longer answers for this post
        if status != 200:
            return None, "http-error"   # a transport problem gets the strike budget
        # 200 with no blob: published, but nothing aired yet — worth another look.
        return None, "no-player-data"
    post = build_post(wp_post, player)
    if post is None:
        return None, "not-a-post"
    return post, "ok"


def _bump_error(db_path: Path, loc: str, note: str, park_now: bool = False,
                requeue: bool = False) -> None:
    """
    Records why a queue entry did not become a post.

    A post the site no longer resolves is known on the first sighting, so it is
    parked; three failed reads is the budget for a transport problem. A drama with
    no player data is neither: the entry is put back in the queue (`scraped = 2`,
    which sync_catalog and the next crawl both pick up) so the episodes get picked
    up on the run after the site publishes them, instead of being lost forever.
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
            # The REST record is what the next crawl reads; a note must not
            # destroy it, or a transient failure turns into a re-fetch.
            record.update(stamp)
        else:
            record = stamp
        conn.execute(
            "UPDATE sitemap_cache SET error_count = error_count + 1, raw_json = ? WHERE loc = ?;",
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
                  delay: float = 0.2, batch_size: int = 20,
                  verbose: bool = True) -> dict:
    """
    Fetches, parses and commits every queued drama.

    ``probe`` HEADs each video URL with the per-host referer rule applied; it
    costs one request per episode and the CDNs rate-limit, so it is opt-in.
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
    if verbose:
        print(f"[*] [{SITE}] {len(rows)} dramas pending "
              f"(workers={workers}, probe={probe}, deep={deep}).", flush=True)

    totals = {"pages": 0, "posts": 0, "releases": 0, "sources": 0,
              "not_indexable": 0, "failed": 0}
    if not rows:
        return totals

    def work(row):
        if STOP_REQUESTED:
            return None
        time.sleep(delay)
        post, verdict = _parse_record(row["loc"], row["raw_json"], row["slug"])
        if post is None:
            return None, verdict
        try:
            return resolve_links(post, probe=probe, deep=deep), verdict
        except Exception as exc:  # keep the catalog even if a probe dies
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
                # STOP_REQUESTED was set before this row was touched: no request
                # was made, so it is not counted as a page read.
                continue
            totals["pages"] += 1
            post, verdict = outcome
            if post is None:
                totals["not_indexable"] += 1
                _bump_error(db_path, queued["loc"], verdict,
                            park_now=verdict in ("removed", "not-a-post"),
                            requeue=verdict == "no-player-data")
                continue
            batch.append(post)
            if len(batch) >= batch_size:
                _flush(db_path, batch, totals)
                batch = []
            if verbose and (done == len(rows) or done % 100 == 0):
                print(f"    ... {done}/{len(rows)} dramas, {totals['sources']} sources",
                      flush=True)
            if STOP_REQUESTED:
                break
        _flush(db_path, batch, totals)

    if verbose:
        print(f"[✓] [{SITE}] dramas={totals['pages']} posts={totals['posts']} "
              f"releases={totals['releases']} sources={totals['sources']} "
              f"declined={totals['not_indexable']} failed={totals['failed']}", flush=True)
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


def parse_page(url: str) -> dict | None:
    """One drama, from its page URL — the CLI's `parse`/`resolve` entry point."""
    segment = urllib.parse.urlsplit(url or "").path.strip("/").split("/")[-1]
    # A page URL carries the slug percent-encoded; _fetch_post_by_slug encodes it
    # once more on its way out, so decoding here is what keeps a CJK slug from
    # becoming %25EA%25B3 and answering "no such post".
    slug = urllib.parse.unquote(segment)
    if not slug:
        return None
    wp_post = _fetch_post_by_slug(slug)
    if wp_post is None:
        return None
    post, _verdict = _parse_record(url, json.dumps(wp_post), slug)
    return post


def stats(db_path: Path | str = DEFAULT_DB_PATH) -> dict:
    conn = sqlite3.connect(db_path, timeout=60)
    try:
        ensure_schema(conn)
        return {
            "queued": conn.execute(
                "SELECT COUNT(*) FROM sitemap_cache WHERE scraped IN (0,2)").fetchone()[0],
            "indexed": conn.execute("SELECT COUNT(*) FROM sitemap_cache WHERE scraped = 1").fetchone()[0],
            "parked": conn.execute("SELECT COUNT(*) FROM sitemap_cache WHERE scraped = -1").fetchone()[0],
            "posts": conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0],
            "adult_flagged": conn.execute("SELECT COUNT(*) FROM posts WHERE is_18_plus = 1").fetchone()[0],
            "animated": conn.execute("SELECT COUNT(*) FROM posts WHERE is_animated = 1").fetchone()[0],
            "with_synopsis": conn.execute("SELECT COUNT(*) FROM posts WHERE synopsis IS NOT NULL").fetchone()[0],
            "releases": conn.execute("SELECT COUNT(*) FROM releases").fetchone()[0],
            "sources": conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0],
            "subtitle_tracks": conn.execute(
                "SELECT COUNT(*) FROM sources WHERE playback_type = 'subtitle'").fetchone()[0],
            "source_status": dict(conn.execute(
                "SELECT status, COUNT(*) FROM sources GROUP BY status").fetchall()),
            "playback_types": dict(conn.execute(
                "SELECT playback_type, COUNT(*) FROM sources GROUP BY playback_type").fetchall()),
            "services": dict(conn.execute(
                "SELECT service, COUNT(*) FROM sources GROUP BY service ORDER BY COUNT(*) DESC")
                .fetchall()),
            "countries": dict(conn.execute(
                "SELECT country, COUNT(*) FROM posts GROUP BY country ORDER BY COUNT(*) DESC")
                .fetchall()),
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="import_kisskh.py",
        description=f"kisskh staging importer ({BASE_URL} -> {DEFAULT_DB_PATH})")
    parser.add_argument("command", nargs="?", default="sync",
                        choices=["sync", "crawl", "parse", "resolve", "stats"])
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--delay", type=float, default=0.2)
    parser.add_argument("--batch-size", type=int, default=20, dest="batch_size")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--url", help="single drama URL for parse/resolve")
    parser.add_argument("--probe", action="store_true",
                        help="HEAD every source row, video and subtitle track alike, "
                             "with the per-host referer rule")
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
        print(json.dumps(stats(db), indent=2, ensure_ascii=False))
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
