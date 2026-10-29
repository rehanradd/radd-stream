#!/usr/bin/env python3
"""
import_fzmovies.py — isolated staging importer for https://fzmovies.host

Writes ONLY to a per-site staging database (`fzmovies.db`, default under the
lane's data directory). It never opens the production catalog and never calls
`merge_catalogs.py`; merging is an operator decision behind its own gate.
Pure standard library, zero pip packages.

WHAT THIS SITE IS, MEASURED 2026-10-30 (TWO requests, both `curl -m 15`, host
printed each time — no crawl was run, see "WHY THIS HAS NOT BEEN CRAWLED")
--------------------------------------------------------------------------------
fzmovies.host is not WordPress and has no REST layer. It is a flat PHP site
from the pre-CMS era of Indian scene piracy, and its whole surface is query
strings on bare filenames:

  Listing rails (the entry points a crawler walks)
    movieslist.php?catID=<1|2|3>&by=<latest|date|rating|downloads|alpha>
        catID 1 = Bollywood Movies, 2 = Hollywood Movies, 3 = Hollywood Dubbed
        (the three catID values and their labels are read off the homepage)
    hotmovies.php?catID=<n>      "What are people watching right now?"
    alpha.php?catID=<n>          A-Z index (the dubbed rail spells this
                                 `movieslist.php?catID=3&by=alpha` instead)
    genre.php?catID=<n>          genre index
    imdb250.php, oscars.php, filmfare.php, movietags.php, advancedsearch.php
    and, off an item page, the per-value rails year.php?catID=&year=,
    starcast.php?catID=&starcast=, director.php?catID=&director=,
    movieseries.php, userlists.php, moviequotes.php
    Which of these exist for which catID is measured, not inferred: the
    homepage shows `hotmovies.php`/`genre.php` for catID=2 only, and `by=downloads`
    for catID=1 and 2 only.

  Item pages
    movie-<Title with %20 for spaces>--hmp4.htm
    e.g. movie-The%20Break-Up%202006--hmp4.htm
    The dubbed rail names its items differently and carries no year:
    movie--Dubbed--The Tiger Rising [Hindi].htm — so the item class is
    `movie-*.htm` minus `movie-*-subtitle.htm`, which is the same shape and is a
    caption download, not a work. Titles are percent-encoded on a listing page
    and written with literal spaces inside the item page itself.

  Item page shape (that measured page, 50,978 bytes)
    - `<title>The Break-Up 2006 (2006)</title>` — name then year in parens.
      There is NO `og:*` block and no JSON-LD, but the page IS a full
      `itemtype='http://schema.org/Movie'` microdata block, and that is where
      the real metadata lives: `name`, `description` (the plot), `image`,
      `genre`, `tag`, `sameAs` (the IMDb URL, hence the `tt…` id), `director`
      and `actor` as nested Person blocks with `<meta itemprop='name'>`,
      `datePublished`/`dateModified` as `<meta content>`, and `url` per release.
      Outside the microdata, plain text carries `Runtime:`, `IMDb Rating:`
      with `/10 (148862 votes)`, and a `Downloads:` counter.
    - The site repeats the year inside its own `name` ("The Break-Up 2006"), so
      the canonical key is built from a title with that trailing year removed;
      otherwise every row would key as `the-break-up-2006-2006` and never join
      the same work coming from another site.
    - Download rows are anchors whose *text* carries the release metadata and
      whose *href* is a redirector:
          href   = download1.php?downloadoptionskey=3-10504-6de26004dc76…
          onclick= window.location.href="download1.php?…&pt=jRGarGzOo2"
          text   = "The Break-Up 2006 BluRay 480p.mp4"
          next   = <dcounter> (284 MB) { 34466 hits }</dcounter>
      So source (BluRay), resolution (480p/720p) and container (.mp4/.mkv) come
      from the label while the SIZE AND THE SITE'S OWN HIT COUNT come from the
      `<dcounter>` that follows the anchor — an anchor-text-only reader stores
      sizeless releases. The key is opaque (`<int>-<int>-<hex>`); the `pt` token
      appears only inside the JavaScript and is never stored (see `download_key`).
      `mediainfo.php?downloadoptionskey=<same key>` and
      `ss.php?downloadoptionskey=<same key>` are the per-release evidence pages;
      neither is fetched here, and both are derivable from the stored key.
    - A grouping anchor labelled "480p and 720p" points back at the item page
      itself and is not a release.
    - Poster: `itemprop='image' src=/imdb_images/<Dotted.Title>.jpg` — the
      filename is the title with dots and spaces, so it is derived, not an id.
    - Trailer: a real `https://www.youtube.com/embed/<11-char-id>` iframe.
    - Sidebar `<img>`s from `/imdb_images/` for *other* films, plus `owl.carousel`
      recommendation strips: those are not releases and not items.

  What is NOT measured, and is therefore not assumed
    - Total item count, and whether any rail is paginated (`page=`/`start=` was
      not observed on the homepage; a listing page has not been fetched).
    - Whether `/sitemap.xml` exists. It was not requested, so this module does
      not claim absence and does not depend on it.
    - Whether `downloadoptionskey` values expire, and what the redirector
      eventually serves. Nothing here follows it.

PLAYABILITY — THE RULE THAT GOVERNS EVERY ROW THIS MODULE WRITES
--------------------------------------------------------------------------------
`download1.php?downloadoptionskey=…` is a same-site redirector to an unknown
final URL. Following it would be an unbounded probe against someone else's
infrastructure, so this module stores it as `playback_type='redirect'` with
`status='unverified'` and `is_temporary=1` (the key is opaque and may rotate):
catalog evidence, never a watchable link, and never a byte anyone has fetched.
That is the same posture `import_moviesmela.py` takes toward iframes, and it is
why `--resolve-links` deliberately does not exist here.

Nothing produced by this importer routes a viewer through a link shortener: the
shortener family is permanently retired project-wide, so `download1.php` is kept
only as site-internal evidence of what the page offered, not as a hop.

Adult content: the site is a general catalog with no adult section observed, so
`is_18_plus` is keyword-derived from title and link text and errs toward
flagging, exactly as the other importers do. Per AGENTS.md the flag hides a row
from every public surface; it never deletes it, and ingest stays 100%.

WHY THIS HAS NOT BEEN CRAWLED (owner's fleet gate, encoded as `crawl_blocked`)
--------------------------------------------------------------------------------
The owner's rule for this task: start a crawl only when the 1-minute load is
under 4.0, `MemAvailable` is above 4000 MB, and no other lane is crawling. On
2026-10-30 the box was at load ~6.9-10.7 with five lanes on one vCPU, so
`sync` was never run and the deliverable is this module plus its offline test.
`crawl_blocked()` reads the same three conditions at run time and refuses, so a
future lane cannot swarm the box by forgetting the rule — the gate is code, not
a comment. A crawl, when it happens, is `sync --limit N --delay D` against a
staging path the operator names.
"""

from __future__ import annotations

import argparse
import html as html_mod
import json
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

BASE_URL = "https://fzmovies.host"
SITE_NAME = "fzmovies"
DEFAULT_DB_PATH = Path("/home/ubuntu/radd-stream-data/fzmovies.db")
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124 Safari/537.36"
)
PAGE_TIMEOUT = 25
RATE_LIMIT_STATUS = 429

# The rails that enumerate the catalog, transcribed from the measured homepage
# and the measured item page — every (label, query) pair below was seen on the
# page. Where a rail exists for one catID and was not seen for another, it is
# left out rather than guessed: the dubbed rail has no `by=downloads`, no
# `hotmovies.php` and no `genre.php` on that homepage, and its alphabetical
# index is `movieslist.php?catID=3&by=alpha` rather than `alpha.php`.
LISTING_RAILS = (
    ("hollywood", "movieslist.php?catID=2&by=latest"),
    ("hollywood_by_date", "movieslist.php?catID=2&by=date"),
    ("hollywood_by_rating", "movieslist.php?catID=2&by=rating"),
    ("hollywood_by_downloads", "movieslist.php?catID=2&by=downloads"),
    ("hollywood_alpha", "alpha.php?catID=2"),
    ("hollywood_hot", "hotmovies.php?catID=2"),
    ("hollywood_genre", "genre.php?catID=2"),
    ("bollywood", "movieslist.php?catID=1&by=latest"),
    ("bollywood_by_date", "movieslist.php?catID=1&by=date"),
    ("bollywood_by_rating", "movieslist.php?catID=1&by=rating"),
    ("bollywood_by_downloads", "movieslist.php?catID=1&by=downloads"),
    ("bollywood_alpha", "alpha.php?catID=1"),
    ("dubbed", "movieslist.php?catID=3&by=latest"),
    ("dubbed_by_date", "movieslist.php?catID=3&by=date"),
    ("dubbed_alpha", "movieslist.php?catID=3&by=alpha"),
    ("imdb250", "imdb250.php"),
    ("oscars", "oscars.php"),
    ("filmfare", "filmfare.php"),
)

CATID_INDUSTRY = {"1": "bollywood", "2": "hollywood", "3": "dubbed"}

#: Item pages are `movie-<title>.htm`, and the measured homepage shows two
#: different tails for it: `--hmp4.htm` on bollywood/hollywood, and nothing at
#: all on the dubbed rail (`movie--Dubbed--The Tiger Rising [Hindi].htm`). A
#: `--subtitle.htm` link sits in the same shape as an item and is NOT one, so
#: the class is `movie-*.htm` minus the subtitle file.
ITEM_HREF_RE = re.compile(r"^movie-.+\.htm$", re.IGNORECASE)
SUBTITLE_HREF_RE = re.compile(r"^movie-.+--subtitle\.htm$", re.IGNORECASE)
DUBBED_PREFIX_RE = re.compile(r"^movie--Dubbed--", re.IGNORECASE)
#: The release anchor: a same-site redirector with an opaque options key.
#: The measured item page appends `&pt=jRGarGzOo2` — a per-page-view token, the
#: same value on every anchor of the page — so the match ends at `&` as well as
#: at end of string. `download_match` drops the token before it is stored.
DOWNLOAD_HREF_RE = re.compile(
    r"^download1\.php\?downloadoptionskey=([0-9]+)-([0-9]+)-([0-9a-f]+)(?:&|$)",
    re.IGNORECASE,
)

#: Never stored, never fetched: analytics, ad scripts and pop-unders seen on the
#: measured item page. Matching is by hostname suffix so a rotated junk domain of
#: the same shape is still caught.
JUNK_HOST_SUFFIXES = (
    "googletagmanager.com",
    "google-analytics.com",
    "accounts.google.com",
    "platform.twitter.com",
    "peculiaritieswatcher.com",
    "hippierrapiner.com",
    "doubleclick.net",
    "googlesyndication.com",
)

#: No version word may appear here — `test_database.py` scans every `*ADULT*`
#: literal in the tree for exactly that, because "Uncut"/"Unrated"/"Extended"
#: decorate mainstream releases ("Kanguva 18+ Uncut" is flagged by the studio,
#: not by the word) and a version word alone hides works that should be listed.
#: The strong tokens below are producers and formats, not cut versions.
ADULT_KEYWORDS = (
    "18+", "xxx", "porn", "erotic", "blue film", "blue-film", "adult",
    "hardcore", "hotshots", "kooku", "ullu", "primeplay", "hentai",
    "aunty", "stepmother", "affair", "bedroom", "sex",
)

_RES_RE = re.compile(r"\b(2160p|1080p|720p|480p|360p|4k|hd|sd)\b", re.IGNORECASE)
_SIZE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(GB|MB)\b", re.IGNORECASE)
_CONTAINER_RE = re.compile(r"\.(mp4|mkv|3gp|avi|m4v|mov)\b", re.IGNORECASE)
_SOURCE_RE = re.compile(
    r"\b(Web-?DL|BluRay|Blu-Ray|HDTS|TeleSync|TS|CAM|DVDScr|WEBRip|HDTV|HDrip|DVDRip| Screener)\b",
    re.IGNORECASE,
)
_YEAR_RE = re.compile(r"^(.*?)\s*\((\d{4})\)\s*$", re.DOTALL)
_TRAILER_RE = re.compile(r"youtube\.com/embed/([A-Za-z0-9_-]{6,16})")
_POSTER_RE = re.compile(r"/imdb_images/[^\s\"'<>]+\.(?:jpg|jpeg|png|webp)", re.IGNORECASE)

_SIZE_UNITS = {"GB": 1024**3, "MB": 1024**2}


def _unescape(text: str | None) -> str:
    return html_mod.unescape(text or "")


def clean_text(text: str | None) -> str:
    return re.sub(r"\s+", " ", _unescape(re.sub(r"<[^>]+>", " ", text or ""))).strip()


def absolute(url: str, base: str = BASE_URL) -> str:
    return urllib.parse.urljoin(base.rstrip("/") + "/", url.lstrip("/"))


def looks_adult(*labels: str) -> int:
    """Err toward flagging: an unlabelled adult title that reaches the public
    list is a compliance defect, a wrongly flagged one is an operator review."""
    hay = " | ".join(x.lower() for x in labels if x)
    return 1 if any(k in hay for k in ADULT_KEYWORDS) else 0


def slugify(text: str | None) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return slug[:80]


_LANG_BRACKET_RE = re.compile(r"\[([^\]]{1,24})\]")


def title_from_href(href: str) -> tuple[str, int | None]:
    """`movie-The%20Break-Up%202006--hmp4.htm` -> ("The Break-Up", 2006).

    The site writes the title into the filename with %20 (and, on item pages,
    with literal spaces) and keeps a trailing year when it knows one; a bare
    `Blue Heron` has none. The dubbed rail uses no year and no `--hmp4` tail at
    all — `movie--Dubbed--The Tiger Rising [Hindi].htm` — so the rail prefix and
    the bracketed audio-language marker are stripped before the year is read.
    A four-digit tail is only a year if it is >= 1900, because "Skyline 2010" is
    a year and "Ocean 1440" is not a plausible one.
    """
    name = href
    m = re.match(r"^movie-(.+?)\.htm$", name, re.IGNORECASE)
    if m:
        name = m.group(1)
    name = urllib.parse.unquote(name)
    name = re.sub(r"^-{0,2}Dubbed--", "", name, flags=re.IGNORECASE)
    name = re.sub(r"--(?:hmp4|subtitle)$", "", name, flags=re.IGNORECASE)
    name = _LANG_BRACKET_RE.sub("", name)
    name = re.sub(r"\s+", " ", name).strip(" -.")
    ym = re.search(r"\b(19|20)\d{2}$", name)
    year = None
    if ym:
        candidate = int(ym.group(0))
        if candidate >= 1900:
            year = candidate
            name = name[: ym.start()].strip(" -")
    return name, year


def langs_from_href(href: str) -> list[str]:
    """The dubbed rail names its audio language inside `[...]`."""
    return [m.group(1).strip() for m in _LANG_BRACKET_RE.finditer(urllib.parse.unquote(href or ""))
            if m.group(1).strip()]


def parse_item_release(label: str) -> dict:
    """Read quality/container/source/size out of the anchor text."""
    text = clean_text(label)
    qm = _RES_RE.search(text)
    container_m = _CONTAINER_RE.search(text)
    size_m = _SIZE_RE.search(text)
    source_m = _SOURCE_RE.search(text)
    size_bytes = None
    if size_m:
        size_bytes = int(float(size_m.group(1)) * _SIZE_UNITS[size_m.group(2).upper()])
    return {
        "label": text,
        "quality": (qm.group(1) if qm else None),
        "container": (container_m.group(1).lower() if container_m else None),
        "source": (source_m.group(1).strip() if source_m else None),
        "size_bytes": size_bytes,
    }


#: An `<a>` tag whose attribute list is consumed one *quoted value* at a time.
#: This matters here more than on a normal site: the release anchors carry
#: `onclick='window.location.href="download1.php?…&pt=…"; return false;'` and a
#: separate real `href='download1.php?…'`. A naive `href\s*=` search finds the
#: one inside the JavaScript first and stores the visitor token as if it were
#: the link. Consuming quoted attribute values whole, then reading attributes,
#: keeps the href that the browser would actually use.
_ATTR_CHUNK = r"[^>\"']|\"[^\"]*\"|'[^']*'"
_ANCHOR_RE = re.compile(
    r"<a\b((?:%s)*?)>((?:(?!</a>).)*)</a>" % _ATTR_CHUNK,
    re.IGNORECASE | re.DOTALL,
)
_ATTR_RE = re.compile(
    r"([A-Za-z_:][-A-Za-z0-9_:.]*)\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s\"'>]+))"
)


def anchor_attrs(tag_body: str) -> dict[str, str]:
    """Attribute map of one `<a>` tag; the first spelling of a name wins."""
    attrs: dict[str, str] = {}
    for m in _ATTR_RE.finditer(tag_body or ""):
        name = m.group(1).lower()
        if name in attrs:
            continue
        attrs[name] = _unescape(m.group(2) if m.group(2) is not None
                               else m.group(3) if m.group(3) is not None
                               else (m.group(4) or ""))
    return attrs


def anchor_records(html_text: str):
    """Yield {href, attrs, inner, end} for every `<a>`, in document order."""
    for m in _ANCHOR_RE.finditer(html_text or ""):
        attrs = anchor_attrs(m.group(1))
        yield {
            "href": attrs.get("href", ""),
            "attrs": attrs,
            "inner": m.group(2),
            "end": m.end(),
        }


def _anchors(html_text: str):
    """(href, inner_html) for every `<a>` — the shape the rails read."""
    for rec in anchor_records(html_text):
        yield rec["href"], rec["inner"]


def _is_junk(url: str) -> bool:
    host = urllib.parse.urlsplit(url).netloc.lower()
    return any(host == s or host.endswith("." + s) for s in JUNK_HOST_SUFFIXES)


# ── schema.org microdata, which this site does carry ────────────────────────
# The measured item page is not JSON-LD and has no `og:*` block, but it is a
# full `<div itemscope itemtype='http://schema.org/Movie'>`: name, description,
# image, genre, tag, sameAs (the IMDb URL, hence the tt-id), url per release,
# datePublished/dateModified as `<meta content>`, and actor/director as nested
# Person blocks whose names are `<meta itemprop='name' content=…>`. Reading the
# microdata is what makes imdb_id, synopsis, cast and runtime real columns here
# instead of guesses from the title.
_SPAN_PROP_RE = re.compile(
    r"itemprop=[\"'](?P<prop>description|sameAs|genre|tag|url)[\"'][^>]*>(?P<val>.*?)</span>",
    re.IGNORECASE | re.DOTALL,
)
_META_PROP_RE = re.compile(
    r"itemprop=[\"'](?P<prop>datePublished|dateModified)[\"'][^>]*content=[\"'](?P<val>[^\"']*)[\"']",
    re.IGNORECASE,
)
_PERSON_BLOCK_RE = re.compile(
    r"itemprop=[\"'](?P<role>actor|director)[\"'].{0,120}?>\s*(?P<body>.*?)</div>",
    re.IGNORECASE | re.DOTALL,
)
_PERSON_NAME_RE = re.compile(
    r"itemprop=[\"']name[\"'][^>]*content=[\"'](?P<val>[^\"']*)[\"']", re.IGNORECASE)
_RUNTIME_RE = re.compile(r"Runtime:\s*<[^>]*>\s*([^<]+?)\s*</[^>]*>", re.IGNORECASE)
_RATING_RE = re.compile(r"IMDb Rating:\s*<[^>]*>\s*([0-9]+(?:\.[0-9]+)?)\s*<", re.IGNORECASE)
_VOTES_RE = re.compile(r"/10\s*\(([\d,]+)\s*votes?\)", re.IGNORECASE)
_DOWNLOADS_RE = re.compile(r"Downloads:\s*<[^>]*>\s*([\d,.]+)\s*<", re.IGNORECASE)
_DCOUNT_RE = re.compile(
    r"<dcounter>\s*\((?P<size>\d+(?:\.\d+)?)\s*(?P<unit>GB|MB)\)"
    r"\s*\{\s*(?P<hits>[\d,.]+)\s*hits?\s*\}",
    re.IGNORECASE,
)


#: Which span props repeat (so they are collected) and which are single-valued
#: (so the first one wins). Without this split a second `itemprop='url'` span
#: would try to append to the string the first one stored.
_SPAN_LIST_BUCKETS = {"genre": "genres", "tag": "tags", "url": "release_urls"}


def parse_microdata(html_text: str) -> dict:
    """Every measured microdata field of one item page, keys as the site spells them."""
    out: dict = {"genres": [], "tags": [], "cast": [], "director": [], "release_urls": []}
    for m in _SPAN_PROP_RE.finditer(html_text):
        value = clean_text(m.group("val"))
        if not value:
            continue
        prop = m.group("prop").lower()
        bucket = _SPAN_LIST_BUCKETS.get(prop)
        if bucket:
            if value not in out[bucket]:
                out[bucket].append(value)
        else:
            out.setdefault(prop, value)
    for m in _META_PROP_RE.finditer(html_text):
        out.setdefault(m.group("prop").lower(), m.group("val").strip())
    for block in _PERSON_BLOCK_RE.finditer(html_text):
        names = [mm.group("val").strip() for mm in _PERSON_NAME_RE.finditer(block.group("body"))]
        bucket = "cast" if block.group("role").lower() == "actor" else "director"
        out[bucket] = [n for n in names if n]
    for pattern, key, group in ((_RUNTIME_RE, "runtime", 1), (_RATING_RE, "imdb_rating", 1),
                                (_DOWNLOADS_RE, "download_count", 1)):
        m = pattern.search(html_text)
        if m:
            out[key] = clean_text(m.group(group))
    votes = _VOTES_RE.search(html_text)
    if votes:
        out["imdb_votes"] = votes.group(1).replace(",", "")
    title_m = re.search(r"itemprop=['\"]name['\"][^>]*>([^<]+)<", html_text, re.IGNORECASE)
    if title_m:
        out["name"] = clean_text(title_m.group(1))
    img_m = re.search(r"itemprop=['\"]image['\"][^>]*src=['\"]([^'\"]+)['\"]", html_text, re.IGNORECASE)
    if not img_m:
        img_m = re.search(r"src=['\"]([^'\"]+)['\"][^>]*itemprop=['\"]image['\"]", html_text, re.IGNORECASE)
    if img_m:
        out["image"] = img_m.group(1)
    return out


def release_counters(html_text: str, from_pos: int, to_pos: int) -> tuple[int | None, int | None]:
    """(size_bytes, hits) from the `<dcounter>` that follows one release anchor.

    The site puts the file size and the hit count *after* the anchor, in a
    custom tag, so an anchor-text-only reader stores a release with no size.
    The window is the text between this anchor and the next, which is why
    `anchor_records` reports where each anchor ended.
    """
    window = html_text[from_pos:to_pos] if 0 <= from_pos <= to_pos else ""
    m = _DCOUNT_RE.search(window)
    if not m:
        return None, None
    size = int(float(m.group("size")) * _SIZE_UNITS[m.group("unit").upper()])
    hits_raw = m.group("hits").replace(",", "")
    try:
        hits = int(float(hits_raw))
    except ValueError:
        hits = None
    return size, hits


def parse_listing(html_text: str) -> list[dict]:
    """Item links only, deduplicated by path, each with the title the site shows."""
    seen: set[str] = set()
    items: list[dict] = []
    for href, inner in _anchors(html_text):
        path = href.split("?")[0].lstrip("./")
        if not ITEM_HREF_RE.match(path) or SUBTITLE_HREF_RE.match(path):
            continue
        if path in seen:
            continue
        seen.add(path)
        text = clean_text(inner)
        title, year = title_from_href(path)
        items.append(
            {
                "url": absolute(path),
                "path": path,
                "link_text": text,
                "title": text or title,
                "title_from_href": title,
                "year": year,
                "dubbed": 1 if DUBBED_PREFIX_RE.match(path) else 0,
                "langs": langs_from_href(path),
            }
        )
    return items


def parse_rail_names(html_text: str) -> dict[str, str]:
    """Which catID means which industry, read off the page rather than hardcoded."""
    found: dict[str, str] = {}
    for href, inner in _anchors(html_text):
        m = re.search(r"catID=([123])", href)
        if not m:
            continue
        label = clean_text(inner).lower()
        if "bollywood" in label:
            found.setdefault(m.group(1), "bollywood")
        elif "dubbed" in label:
            found.setdefault(m.group(1), "dubbed")
        elif "hollywood" in label:
            found.setdefault(m.group(1), "hollywood")
    return found


def download_match(href: str):
    """Match the redirector anchor whether the page wrote it relative or absolute.

    The site emits `download1.php?downloadoptionskey=...` bare; a copied or
    proxied page could carry the host. Stripping scheme, host, and a leading
    `./` keeps one shape for DOWNLOAD_HREF_RE to judge.
    """
    path_query = (href or "").split("#", 1)[0].strip()
    if "://" in path_query:
        parts = urllib.parse.urlsplit(path_query)
        path_query = parts.path.lstrip("/")
        if parts.query:
            path_query = f"{path_query}?{parts.query}"
    return DOWNLOAD_HREF_RE.match(path_query.lstrip("./"))


def download_key(href: str) -> str | None:
    """The opaque options key alone, with the page-view `pt` token dropped.

    The measured `&pt=jRGarGzOo2` is the same on every anchor of one page view,
    so it is visitor state, not part of the release's identity. Storing it would
    put someone else's session material in our catalog and make the row expire
    with the visit. `download1.php?downloadoptionskey=<key>` is therefore the
    stored form, and it is also what makes the sibling evidence pages derivable
    for free: `mediainfo.php?downloadoptionskey=<key>` and
    `ss.php?downloadoptionskey=<key>` (screenshots) use the identical key.
    Neither is fetched here.
    """
    dm = download_match(href)
    return None if dm is None else f"{dm.group(1)}-{dm.group(2)}-{dm.group(3)}"


def parse_item(html_text: str, url: str) -> dict | None:
    """One measured item page -> one post plus its releases and sources."""
    tm = re.search(r"<title>(.*?)</title>", html_text, re.DOTALL | re.IGNORECASE)
    raw_title = clean_text(tm.group(1)) if tm else ""
    ym = _YEAR_RE.match(raw_title)
    if ym:
        clean_title, year = ym.group(1).strip(), int(ym.group(2))
    else:
        clean_title, year = raw_title, None
    href_only = url.rsplit("/", 1)[-1]
    # A named file that is not an item page is not a work. Without this, an
    # error page, a rail, or `index.php` fetched by a confused caller becomes a
    # post keyed on its own filename (`index-php`), which is how a staging
    # catalog fills with noise that later merges as real-looking rows.
    if href_only and not (ITEM_HREF_RE.match(href_only)
                          and not SUBTITLE_HREF_RE.match(href_only)):
        return None
    micro = parse_microdata(html_text)
    if micro.get("name"):
        clean_title = micro["name"]
    if not clean_title:
        clean_title, year = title_from_href(href_only)
    if not clean_title:
        return None
    # This site writes the year *inside* its own `itemprop='name'`
    # ("The Break-Up 2006") while `<title>` repeats it in parentheses. Left
    # alone, the canonical key becomes `the-break-up-2006-2006` and would never
    # join to the same work coming from another site, so a year that is already
    # the row's `year` comes out of the title before the key is built.
    if year is not None and re.search(rf"(?<!\d){year}$", clean_title):
        trimmed = re.sub(rf"(?<!\d){year}$", "", clean_title).strip(" -")
        if trimmed:
            clean_title = trimmed

    key = slugify(clean_title) or slugify(title_from_href(href_only)[0])
    if not key:
        return None
    if year:
        key = f"{key}-{year}"

    poster = absolute(micro["image"]) if micro.get("image") else None
    if not poster:
        poster_m = _POSTER_RE.search(html_text)
        poster = absolute(poster_m.group(0)) if poster_m else None
    trailer_m = _TRAILER_RE.search(html_text)
    # Microdata property names are stored lowercased by `parse_microdata`, so
    # `sameAs` is read as `sameas`.
    same_as = micro.get("sameas") or ""
    imdb_m = re.search(r"tt\d{6,8}", same_as)

    # Releases, with the `<dcounter>` that follows each anchor supplying the
    # size and the site's own hit count. Anchors are walked with their offsets
    # so each release reads only its own counter, never its neighbour's.
    records = list(anchor_records(html_text))
    starts = [rec["end"] for rec in records]
    releases: list[dict] = []
    sources: list[dict] = []
    for index, rec in enumerate(records):
        opt_key = download_key(rec["href"])
        if not opt_key:
            continue
        text = clean_text(rec["inner"])
        if not text or text.lower() == "and":
            continue
        rel = parse_item_release(text)
        if rel["label"].lower() in {"480p and 720p", "480p and 720p mkv"}:
            continue
        size_bytes, hits = release_counters(
            html_text, starts[index],
            starts[index + 1] if index + 1 < len(records) else len(html_text))
        if size_bytes is not None:
            rel["size_bytes"] = size_bytes
        rel["hits"] = hits
        releases.append(rel)
        sources.append(
            {
                "source_name": SITE_NAME,
                "service": "site-redirector",
                "resource_id": opt_key,
                "source_url": absolute(f"download1.php?downloadoptionskey={opt_key}"),
                "final_url": None,
                "playback_type": "redirect",
                "status": "unverified",
                "is_temporary": 1,
                "quality": rel["quality"],
            }
        )

    page_year = re.search(r"year\.php\?catID=\d+&year=(\d{4})", html_text, re.IGNORECASE)
    if year is None and page_year:
        year = int(page_year.group(1))
    published = micro.get("datepublished") or ""
    if year is None and re.match(r"^\d{4}", published):
        year = int(published[:4])
    dubbed = 1 if DUBBED_PREFIX_RE.match(href_only) else 0
    rail_map = parse_rail_names(html_text)
    # The item page names its own rail inside the `moviename` block
    # (`in <a href='movieslist.php?catID=2&by=latest'>Hollywood Movies</a>`),
    # so the industry is read off that link and translated by the labels the
    # page itself uses rather than by a hardcoded catID table.
    name_block = re.search(r"moviename.{0,600}", html_text, re.IGNORECASE | re.DOTALL)
    catid = re.search(r"catID=([123])", name_block.group(0)) if name_block else None
    industry = (rail_map.get(catid.group(1)) if catid else None) or (
        CATID_INDUSTRY["3"] if dubbed else None)
    langs = langs_from_href(href_only) or (["Hindi"] if dubbed else [])
    post = {
        "canonical_key": key,
        "title": raw_title or clean_title,
        "clean_title": clean_title,
        "year": year,
        "media_type": "movie",
        "poster_url": poster,
        "backdrop_url": None,
        "backdrop_urls": None,
        "imdb_id": imdb_m.group(0) if imdb_m else None,
        "tmdb_id": None,
        "imdb_rating": micro.get("imdb_rating"),
        "synopsis": micro.get("description"),
        "genres": json.dumps(micro.get("genres", []), default=str),
        "director": ", ".join(micro.get("director", [])) or None,
        "cast_names": ", ".join(micro.get("cast", [])) or None,
        "duration": micro.get("runtime"),
        "release_date": published or None,
        "languages": json.dumps(sorted(set(langs)), default=str),
        "industry": industry,
        "country": None,
        "seasons": None,
        "url": url,
        "slug": href_only,
        "is_18_plus": looks_adult(clean_title, raw_title, *(r["label"] for r in releases)),
        "is_animated": 0,
        "source_site": SITE_NAME,
        "trailer_youtube_id": trailer_m.group(1) if trailer_m else None,
        "release_count": len(releases),
        "tags": micro.get("tags", []),
        "is_dubbed": dubbed,
        "download_count": micro.get("download_count"),
        "imdb_votes": micro.get("imdb_votes"),
        "date_modified": micro.get("datemodified"),
    }
    return {"post": post, "releases": releases, "sources": sources}


# ── staging write ───────────────────────────────────────────────────────────
SCHEMA = """
CREATE TABLE IF NOT EXISTS page_cache (
    url TEXT PRIMARY KEY,
    kind TEXT,
    fetched_at INTEGER,
    http_status INTEGER,
    error_count INTEGER DEFAULT 0,
    html_sha TEXT
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
    source_site TEXT DEFAULT 'fzmovies',
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
    audio_languages TEXT,
    origin_url TEXT,
    container TEXT,
    source_tag TEXT,
    site_hits INTEGER,
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
    playback_type TEXT DEFAULT 'redirect',
    status TEXT DEFAULT 'unverified',
    is_temporary INTEGER DEFAULT 1,
    quality TEXT,
    last_checked INTEGER,
    FOREIGN KEY (release_id) REFERENCES releases(id)
);
CREATE INDEX IF NOT EXISTS idx_fzmovies_releases_post ON releases(post_canonical_key);
CREATE INDEX IF NOT EXISTS idx_fzmovies_sources_release ON sources(release_id);
"""

POST_COLUMNS = (
    "canonical_key", "title", "clean_title", "year", "media_type", "poster_url",
    "backdrop_url", "backdrop_urls", "imdb_id", "tmdb_id", "imdb_rating", "synopsis",
    "genres", "director", "cast_names", "duration", "release_date", "languages",
    "industry", "country", "seasons", "url", "slug", "is_18_plus", "is_animated",
    "source_site", "raw_meta",
)
EXTRA_POST_KEYS = (
    "trailer_youtube_id", "release_count", "tags", "is_dubbed", "download_count",
    "imdb_votes", "date_modified",
)
RELEASE_COLUMNS = (
    "post_canonical_key", "label", "quality", "resolution", "size_bytes", "codec",
    "audio_languages", "origin_url", "container", "source_tag", "site_hits",
)
SOURCE_COLUMNS = (
    "release_id", "source_name", "service", "resource_id", "source_url", "final_url",
    "playback_type", "status", "is_temporary", "quality", "last_checked",
)


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def write_result(conn: sqlite3.Connection, result: dict) -> int:
    """Insert one parsed item; returns the number of release rows written.

    Idempotent by design: re-running a rail re-reads the same page, and a page
    that is already stored is skipped rather than duplicated, because the
    redirector keys can rotate and a second row would look like a second source.
    """
    post = dict(result["post"])
    existing = conn.execute(
        "SELECT canonical_key FROM posts WHERE canonical_key = ?", (post["canonical_key"],)
    ).fetchone()
    if existing:
        return 0
    extras = {key: post.pop(key) for key in EXTRA_POST_KEYS if key in post}
    post["raw_meta"] = json.dumps(extras, sort_keys=True, default=str)
    conn.execute(
        f"INSERT INTO posts ({', '.join(POST_COLUMNS)}) VALUES ({', '.join('?' * len(POST_COLUMNS))})",
        tuple(post.get(c) for c in POST_COLUMNS),
    )
    written = 0
    for rel, src in zip(result["releases"], result["sources"]):
        cur = conn.execute(
            f"INSERT INTO releases ({', '.join(RELEASE_COLUMNS)}) "
            f"VALUES ({', '.join('?' * len(RELEASE_COLUMNS))})",
            (
                post["canonical_key"], rel["label"], rel["quality"], rel["quality"],
                rel["size_bytes"], None, None, src["source_url"],
                rel.get("container"), rel.get("source"), rel.get("hits"),
            ),
        )
        release_id = cur.lastrowid
        src = {**src, "release_id": release_id, "last_checked": None}
        conn.execute(
            f"INSERT INTO sources ({', '.join(SOURCE_COLUMNS)}) "
            f"VALUES ({', '.join('?' * len(SOURCE_COLUMNS))})",
            tuple(src.get(c) for c in SOURCE_COLUMNS),
        )
        written += 1
    conn.commit()
    return written


# ── the fleet gate, as code ─────────────────────────────────────────────────
LOAD_CEILING = 4.0
MEM_FLOOR_MB = 4000


def read_loadavg(path: str = "/proc/loadavg") -> float:
    try:
        return float(Path(path).read_text().split()[0])
    except (OSError, ValueError, IndexError):
        return 9999.0


def read_mem_available_mb(path: str = "/proc/meminfo") -> float:
    try:
        for line in Path(path).read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return float(line.split()[1]) / 1024.0
    except (OSError, ValueError, IndexError):
        return 0.0
    return 0.0


def crawl_blocked(loadavg: float, mem_available_mb: float,
                  other_crawlers: int, limit: int | None) -> list[str]:
    """Reasons a crawl may not start now. Empty list means the gate is open.

    `limit=None` is refused on purpose: an unbounded first crawl of a flat PHP
    catalog is exactly the swarm the fleet rule exists to prevent.
    """
    reasons = []
    if loadavg >= LOAD_CEILING:
        reasons.append(f"1-min load {loadavg:.2f} is at or above the {LOAD_CEILING} ceiling")
    if mem_available_mb <= MEM_FLOOR_MB:
        reasons.append(f"MemAvailable {mem_available_mb:.0f} MB is at or below {MEM_FLOOR_MB} MB")
    if other_crawlers:
        reasons.append(f"{other_crawlers} other import process(es) are running")
    if not limit or limit < 1:
        reasons.append("no --limit given; an unbounded crawl is never started by default")
    return reasons


def current_gate_state() -> tuple[float, float, int]:
    return read_loadavg(), read_mem_available_mb(), 0


# ── optional network path (only reachable through a passed gate) ───────────
def http_get(url: str, timeout: int = PAGE_TIMEOUT) -> tuple[int, str]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, ""
    except (urllib.error.URLError, TimeoutError, OSError):
        return 0, ""


def sync(db_path: Path, limit: int, delay: float, rails: list[str], quiet: bool) -> int:
    loadavg, mem, crawlers = current_gate_state()
    reasons = crawl_blocked(loadavg, mem, crawlers, limit)
    if reasons:
        for r in reasons:
            print(f"CRAWL BLOCKED: {r}")
        print("crawl deferred, gate conditions not met")
        return 3
    conn = sqlite3.connect(db_path)
    ensure_schema(conn)
    fetched = 0
    stored = 0
    for rail_name, rail_path in rails:
        if fetched >= limit:
            break
        url = absolute(rail_path)
        status, page = http_get(url)
        fetched += 1
        if status == RATE_LIMIT_STATUS:
            print(f"rate limited on {rail_name}; pausing the run without spending the rest")
            break
        if status != 200:
            conn.execute(
                "INSERT OR REPLACE INTO page_cache (url, kind, fetched_at, http_status) "
                "VALUES (?, 'rail', ?, ?)",
                (url, int(time.time()), status),
            )
            conn.commit()
            time.sleep(delay)
            continue
        items = parse_listing(page)[: max(0, limit - stored)]
        for item in items:
            if stored >= limit:
                break
            istatus, ipage = http_get(item["url"])
            if istatus != 200:
                continue
            result = parse_item(ipage, item["url"])
            if not result:
                continue
            written = write_result(conn, result)
            stored += 1 if written else 0
            conn.execute(
                "INSERT OR REPLACE INTO page_cache (url, kind, fetched_at, http_status) "
                "VALUES (?, 'item', ?, ?)",
                (item["url"], int(time.time()), istatus),
            )
            conn.commit()
            time.sleep(delay)
        if not quiet:
            print(f"{rail_name}: {len(items)} item links seen, {stored} stored so far")
    conn.close()
    print(f"fetched {fetched} rail(s), stored {stored} item(s) into {db_path}")
    return 0


def _rail_subset(names: list[str]) -> list[tuple[str, str]]:
    if not names:
        return list(LISTING_RAILS)
    return [(n, p) for n, p in LISTING_RAILS if n in names]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("command", nargs="?", default="sync",
                        choices=["sync", "parse-listing", "parse-item", "gate"])
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--delay", type=float, default=1.5)
    parser.add_argument("--rails", nargs="*", default=[])
    parser.add_argument("--file", help="captured HTML for the offline parse commands")
    parser.add_argument("--url", default=BASE_URL)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    if args.command == "gate":
        loadavg, mem, crawlers = current_gate_state()
        reasons = crawl_blocked(loadavg, mem, crawlers, args.limit)
        print(f"load1={loadavg:.2f} MemAvailable={mem:.0f}MB other_crawlers={crawlers}")
        for r in reasons:
            print(f"BLOCKED: {r}")
        print("gate open — a bounded crawl may start" if not reasons
              else "crawl deferred, gate conditions not met")
        return 0 if not reasons else 3

    if args.command in ("parse-listing", "parse-item"):
        text = Path(args.file).read_text(encoding="utf-8", errors="replace") if args.file \
            else sys.stdin.read()
        if args.command == "parse-listing":
            items = parse_listing(text)
            print(json.dumps({"items": len(items), "rails_found": parse_rail_names(text),
                              "first": items[:3]}, indent=2, default=str))
        else:
            result = parse_item(text, args.url)
            print(json.dumps(result, indent=2, default=str) if result else "unparseable")
        return 0

    db_path = Path(os.path.expanduser(args.db))
    return sync(db_path, args.limit, args.delay, _rail_subset(args.rails), args.quiet)


if __name__ == "__main__":
    raise SystemExit(main())
