#!/usr/bin/env python3
"""
Fast_Fetch Database Viewer & Site Explorer v2.0
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Modern, responsive local web dashboard to:
1. Explore all saved database releases with season/episode filters & direct CDN copy.
2. Search through all 14,025 site posts with 1-click on-demand scraping & link unwrapping.
3. Export VLC / M3U streaming playlists for any series or movie.

Usage:
  python viewer.py [PORT]     (Default: http://localhost:8080)
"""

from __future__ import annotations
import sys
import json
import sqlite3
import threading
import time
import urllib.parse
import urllib.request
from contextlib import contextmanager
import os
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

import redact
import db_pragmas  # serve-path SQLite pragmas (Session 125)
import tiers
import live_tv
import api_v2
import catalog_v2
import engagement
import accounts_api
import payments
import admin_panel
import media_search
import panel_feed
import contact_intake
import fts_posts
import search_fuzzy
import did_you_mean
import title_clean
import mood_search
import works
import usage_stats

if sys.platform.startswith("win"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).parent.resolve()
try:                    # single brand source: config.py derives these from brand.properties
    from config import BASE_DIR, DB_PATH
except ImportError:     # standalone fallback keeps the historical behaviour
    _env_db = os.environ.get("RADD_DB_PATH")
    DB_PATH = Path(_env_db) if _env_db else BASE_DIR / "fast_fetch.db"
_SCHEMA_READY_FOR = None

#: Where our own absolute URLs (stream/art handles, playlist entries) are
#: rooted. Empty means "whatever the request came in on", which is correct
#: behind the reverse proxy and wrong only for a bare `curl localhost`.
PUBLIC_BASE_URL = os.environ.get("RADD_PUBLIC_BASE_URL", "").rstrip("/")
#: The operator-only dashboard needs the full rows; the public port never has
#: them. Set per server instance in start_server(), never from a request.
OPERATOR_PORT = int(os.environ.get("RADD_INTERNAL_PORT", "8081"))

#: The public port answers 404 for these; they name or drive upstreams.
OPERATOR_ONLY_ROUTES = frozenset({
    "/api/sitemap",      # upstream page URLs, by site
    "/api/fetch",        # scrape any caller-supplied URL (also an SSRF)
    "/api/heal",         # re-resolve a post's links against upstreams
    "/api/health-check", # probe upstreams
    "/api/v1/rules",     # client-side bridge-unwrapping recipes
    # The whole catalog in one response, releases and links included. Even fully
    # projected it is a bulk clone of our collection and, at 109k posts, a
    # self-inflicted denial of service on this box. It is the dashboard's feed
    # only — ANDROID_INTEGRATION.md lists it as "not a client integration point"
    # — and clients use the paginated /api/v1/posts.
    "/api/data",
})

#: Same answer as a route above, but for a whole subtree: `/admin` is one page and
#: five JSON screens under it, and listing them individually is how one of them
#: gets forgotten when the panel grows. Reachability is this prefix plus the
#: loopback bind plus nginx never proxying `/admin`; `admin_panel._gate` is the
#: token lock on that already-localhost-only door, not a login.
#:
#: Every route on this port also requires the operator bearer token — see
#: `_operator_gate` and `admin_panel.gate_operator_port`, fail-closed when
#: `RADD_ADMIN_TOKEN` is unset. Say the order, because getting it backwards is how
#: this surface gets mis-described: **loopback is the boundary** (both ports bind
#: to 127.0.0.1 and nginx forwards neither, so nothing outside this VM can reach
#: any of it), and the token is the credential checked *inside* that boundary,
#: second and after the peer address. A token does not make the dashboard
#: reachable, so the dashboard is not "token-gated" — see root AGENTS.md, which
#: forbids that wording, and `docs/ADMIN_PANEL_ACCESS.md` for the measurement.
OPERATOR_ONLY_PREFIXES = ("/admin", "/operator")

#: The two byte paths a playback actually travels, counted for the operator's
#: usage report. `/api/m3u` is deliberately absent: it is an operator route, and
#: a panel's own smoke test is not a user pressing play.
PLAYBACK_ROUTES = frozenset({"/api/v1/stream", "/api/v1/download"})

#: The play bucket's limit, refreshed from the operator's
#: `rate_limit_play_per_min` tuning knob at most once a minute. The gate
#: runs on every public request, and a panel read on every one of those
#: would be a SQLite open per request; a minute-old knob is fresh enough
#: for a rate limit, and the shipped 30 is the answer when the panel is
#: unwired. The cache is module state, read and written by the request
#: threads; the worst a race does is two threads refreshing the same
#: value, which is idempotent.
_PLAY_LIMIT_CACHE = {"value": 30, "at": 0.0}
_PLAY_LIMIT_TTL_SECONDS = 60.0


def _play_limit_per_min():
    """The play bucket's per-minute limit, from the operator's knob.

    The panel's `rate_limit_play_per_min` (clamped to the panel's own
    bounds, 10..120), cached for a minute. An unwired panel answers the
    shipped 30. Never raises.
    """
    now = time.time()
    if now - _PLAY_LIMIT_CACHE["at"] < _PLAY_LIMIT_TTL_SECONDS:
        return _PLAY_LIMIT_CACHE["value"]
    try:
        value = panel_feed.tuning_knob(
            name="rate_limit_play_per_min", default=30)
    except Exception:
        value = 30
    if not isinstance(value, int) or value < 1:
        value = 30
    _PLAY_LIMIT_CACHE["value"] = value
    _PLAY_LIMIT_CACHE["at"] = now
    return value

#: CORS lives in redact so the v1 and v2 edges share one allow-list (§16.7).
cors_headers_for = redact.cors_headers_for


_SIGNING_SECRET = None


def signing_secret() -> str:
    """The process-wide handle-signing secret. Fails closed.

    Delegates to :func:`redact.stream_secret`, which raises when no secret can
    be read or durably generated (audit critical 4: never a constant fallback).
    A failed lookup is not cached — the next signing attempt re-resolves, so a
    transient storage failure never freezes the process onto any fallback key.
    The value is never logged or returned in error text."""
    global _SIGNING_SECRET
    if _SIGNING_SECRET is None:
        _SIGNING_SECRET = redact.stream_secret(DB_PATH)
    return _SIGNING_SECRET


#: The fallback lifetime of a temporary bridge token, in seconds. This is the old
#: constant, kept only as the *ceiling* for links whose hoster declared nothing;
#: a measured window always beats it.
TEMPORARY_TOKEN_CEILING = 6 * 3600

#: Public shortener APIs. Their API tokens are appended server-side from
#: `admin_panel.shortener_targets`; a client is only ever told whether one is
#: configured, never the credential itself.
SHORTENER_ENDPOINTS = {
    "shrinkme": "https://shrinkme.io/api",
    "droplink": "https://droplink.co/api",
}
SHORTENER_TIMEOUT_SECONDS = 6.0
SHORTENER_MAX_RESPONSE_BYTES = 64 * 1024
#: New media URLs rotate to a different configured network each hour. Cached
#: URLs do not rotate; the cache exists so a repeat download spends no quota.
SHORTENER_ROTATION_SECONDS = 3600


def stream_expires_in(res: dict) -> float | None:
    """Seconds a just-handed-out stream URL is good for, measured where possible.

    Order of honesty:
      1. `expires_in` from `resolve_live_source` — read off the hoster's own
         `Cache-Control: max-age` / `Expires` for the URL we are serving (A5);
      2. for a temporary token with no declared window, the 6-hour bridge ceiling
         less the time it has already been alive, so a client is never promised a
         longer life than the token actually has left;
      3. None for a permanent link — it has no expiry to report, and inventing one
         is exactly what the made-up bundle TTL used to do.
    """
    measured = res.get("expires_in")
    if measured is not None:
        try:
            return max(0.0, float(measured))
        except (TypeError, ValueError):
            pass
    if not res.get("is_temporary"):
        return None
    expires_at = res.get("expires_at")
    if expires_at is not None:
        try:
            return max(0.0, float(expires_at) - time.time())
        except (TypeError, ValueError):
            pass
    return float(TEMPORARY_TOKEN_CEILING)


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        # Session 125: serve-path pragmas via the shared helper (64 MiB
        # cache, mmap, temp_store, busy_timeout 30000 like
        # fast_fetch.get_db — this connection used to run on sqlite's
        # 5 s default). One helper for every serve path.
        db_pragmas.apply_serve_pragmas(conn)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _ensure_schema():
    global _SCHEMA_READY_FOR
    if _SCHEMA_READY_FOR == DB_PATH:
        return
    import fast_fetch
    fast_fetch.init_db(DB_PATH)
    redact.set_needles(redact.site_needles(DB_PATH), redact.site_text_needles(DB_PATH))
    with get_db() as conn:
        ensure_shortened_links(conn)
    _SCHEMA_READY_FOR = DB_PATH


def _public_base(handler=None) -> str:
    """Absolute root for URLs we hand out. Our own Host header, never an
    upstream's — this is the only host a client is ever told about."""
    if PUBLIC_BASE_URL:
        return PUBLIC_BASE_URL
    if handler is not None:
        host = str(handler.headers.get("Host") or "").strip()
        proto = str(handler.headers.get("X-Forwarded-Proto") or "").strip().lower() or "http"
        if host:
            return f"{proto}://{host}"
    return ""


def link_view(row, base_url: str = "") -> dict:
    """One `download_sources` row as the public may see it: our own opaque
    handle, our own classification, and nothing that names a hoster."""
    link = redact.project(row, "link")
    link["stream_id"] = redact.mint_token(row["id"], signing_secret())
    # The only honest thing a user may be told about *which* server plays: how it
    # behaves, not who runs it. Phase 2 of the app builds "1080p · Fast server"
    # from this plus the print's quality.
    resumable = bool(link.get("is_resumable"))
    link["label"] = "Fast direct" if resumable else "Standard"
    # How the copy behaves, in our own words. The ledger's `playback_type` is a
    # scraper's vocabulary ("url", "iframe"); a client only needs to know whether
    # our player can start it, must resolve it first, or cannot play it here.
    # "external" — not "embed", which is a real hoster name in this ledger and
    # would trip the sentinel scan that protects every other response.
    kind = {"direct": "direct", "url": "resolve", "download": "download",
            "iframe": "external"}.get(str(row["playback_type"] or "").lower(),
                                      "resolve")
    if kind == "external":
        # Session 107: an iframe our own server can unwrap is not external —
        # the resolver turns it into a playlist or file, so the client must
        # resolve it first. Anything else stays external. The service name
        # never reaches the response; only the kind changes.
        service = str(row["service"]) if "service" in row.keys() else ""
        if service.strip().casefold() in catalog_v2._SERVER_RESOLVABLE_SERVICES:
            kind = "resolve"
    link["kind"] = kind
    # Audit critical 10: a measured verdict outranks the ingest label. A row the
    # healer or a 404 marked dead/broken/gone/expired is not playable, whatever
    # its kind says.
    ledger_state = str(row["status"] or "").strip().lower() \
        if "status" in row.keys() else ""
    link["playable"] = (kind in ("direct", "resolve")
                        and ledger_state not in tiers.UNPLAYABLE_STATES)
    if base_url:
        link["play_url"] = (f"{base_url.rstrip('/')}/api/v1/stream"
                            f"?id={link['stream_id']}")
    return link


#: What the operator's ledger view publishes instead of a playable field on a
#: flagged work. Spelled out so the panel says what happened rather than showing
#: an empty button the operator has to debug.
WITHHELD_NOTE = "18+ — stored, never played here"

#: The columns that ARE a way to watch or pull a work without asking this service
#: anything: the hoster page we scraped, the URL it resolved to, the hoster's own
#: file id (`service` is kept, and `service` + `resource_id` is how a pixeldrain
#: or hubcloud link is rebuilt by hand), and the intermediate bridge a player
#: follows. Root `AGENTS.md` allows the operator to *see* a flagged row — the
#: `🔞 18+ ADULT` badge is the audit of the flag — and forbids the panel emitting
#: a stream or download handle for it. `/api/v1/stream` and `/api/v1/download`
#: already refuse (`redact.link_is_adult`, unknown id ⇒ refuse), so this is not
#: the enforcement; it is the projection not putting a raw upstream URL on a page
#: when the refusal behind it is the only thing between that URL and a play.
#: The stored rows are untouched — this edits the JSON, never the ledger.
_WITHHELD_PLAYABLE = ("source_url", "final_url", "resource_id", "intermediate_url")


def _withhold_playable(row) -> dict:
    """One ledger row as the operator sees it when the row is flagged: everything
    except what could be pasted into a browser. Health, status, size, mime, the
    hoster's name and the row's own id stay, so the audit still works."""
    clean = {key: value for key, value in dict(row).items()
             if key not in _WITHHELD_PLAYABLE}
    clean["playback_withheld"] = WITHHELD_NOTE
    return clean


#: Extensions a download may be named with. The mime comes from a hoster and a
#: filename built from it ends up in a `Content-Disposition` header, so only a
#: fixed table may contribute characters — never the value itself.
_DOWNLOAD_EXTENSIONS = {
    "video/mp4": ".mp4",
    "video/x-matroska": ".mkv",
    "video/matroska": ".mkv",
    "video/webm": ".webm",
    "video/quicktime": ".mov",
    "video/x-msvideo": ".avi",
    "video/mp2t": ".ts",
    "video/mpeg": ".mpg",
    "application/vnd.apple.mpegurl": ".m3u8",
    "application/x-mpegurl": ".m3u8",
    "audio/mpeg": ".mp3",
    "audio/mp4": ".m4a",
}


def download_filename(stream_id: str, mime_type, url_hint=None) -> str:
    """A safe attachment name for the file behind a stream handle.

    The handle is already opaque and URL-safe; the only variable part is the
    extension, chosen from [_DOWNLOAD_EXTENSIONS] rather than copied."""
    mime = str(mime_type or "").split(";", 1)[0].strip().lower()
    extension = _DOWNLOAD_EXTENSIONS.get(mime)
    if extension is None and url_hint:
        try:
            from current_hosts import download_extension_for as _ext
            extension = _ext(mime_type, url_hint)
        except Exception:
            extension = ".bin"
    if extension is None:
        extension = ".bin"
    return f"radd-{str(stream_id)[:12]}{extension}"


def download_descriptor(source_id: int, res: dict, base_url: str = "") -> dict:
    """The public JSON answer to `GET /api/v1/download`: what to fetch and how.

    Same provenance rule as the stream route: the descriptor names our own
    handle and our own redirector, never the hoster or the upstream file URL.
    The bytes still move through nobody — a caller follows `download_url` and
    the 302 points at the resolved media URL."""
    token = redact.mint_token(int(source_id), signing_secret())
    descriptor = {
        "success": True,
        "stream_id": token,
        "kind": "download",
        "filename": download_filename(token, res.get("mime_type"), res.get("url")),
        "mime_type": res.get("mime_type"),
        "file_size_bytes": res.get("file_size_bytes"),
        "resumable": bool(res.get("is_resumable")),
        "expires_in": stream_expires_in(res),
    }
    if base_url:
        descriptor["download_url"] = (f"{base_url.rstrip('/')}/api/v1/download"
                                      f"?id={token}&redirect=1")
    return descriptor


# ── free-tier download shorteners ────────────────────────────────────────────


def ensure_shortened_links(conn) -> None:
    """The free-tier short-link cache. `original_url` is the key, so one media
    URL is shortened once no matter how many viewers request it."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS cat_shortened_links ("
        "original_url TEXT PRIMARY KEY, shortener_name TEXT, "
        "shortened_url TEXT, created_at INTEGER)")


def cached_shortened_link(conn, original_url: str) -> str | None:
    row = conn.execute(
        "SELECT shortened_url FROM cat_shortened_links WHERE original_url = ?",
        (original_url,)).fetchone()
    return str(row[0]) if row and row[0] else None


def cache_shortened_link(conn, original_url: str, shortener_name: str,
                         shortened_url: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO cat_shortened_links"
        "(original_url, shortener_name, shortened_url, created_at)"
        " VALUES(?, ?, ?, ?)",
        (original_url, shortener_name, shortened_url, int(time.time())))


def rotate_shortener_targets(targets, *, now=None) -> list:
    """Order configured `(network, token)` pairs for the current rotation window.

    Rotating by the wall clock is stable for every request inside the window and
    advances without stored state, so two workers cannot disagree about which
    network is "next". A network that fails is skipped by the caller, which then
    tries the rest in this same order."""
    if not targets:
        return []
    offset = int((time.time() if now is None else float(now))
                 // SHORTENER_ROTATION_SECONDS) % len(targets)
    return list(targets[offset:]) + list(targets[:offset])


def _shortened_from_body(raw: bytes, original_url: str) -> str | None:
    """The shortened URL in a shortener reply, or None when it is not one.

    ShrinkMe and DropLink both answer `{"status": "success", "shortenedUrl":
    "..."}`, but a shortener is a third party that may change its envelope; the
    keys below are the shapes those two have used. Anything that is not an
    absolute http(s) URL distinct from the input is refused rather than cached,
    so a malformed reply can never become a redirect target."""
    text = raw.decode("utf-8", "replace").strip()
    candidate = None
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        data = None
    if isinstance(data, dict):
        status = str(data.get("status") or "").strip().lower()
        if status and status not in ("success", "ok", "1", "true"):
            return None
        for key in ("shortenedUrl", "shortened_url", "shortUrl", "short_url",
                    "result", "url"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                candidate = value.strip()
                break
    elif isinstance(data, str):
        candidate = data.strip()
    elif text.startswith(("http://", "https://")):
        candidate = text.split()[0]
    if not candidate or candidate == original_url:
        return None
    parsed = urllib.parse.urlparse(candidate)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    return candidate


def call_shortener(network: str, token: str, original_url: str, *,
                   timeout: float = SHORTENER_TIMEOUT_SECONDS) -> str | None:
    """Ask one shortener to shorten `original_url`; None on any failure.

    The API token travels in the query string to the network's fixed endpoint,
    never to the caller, and no request URL is logged here — a token in a log is
    a token leaked to anyone who reads it."""
    endpoint = SHORTENER_ENDPOINTS.get(str(network or "").lower())
    if not endpoint or not token or not original_url:
        return None
    query = urllib.parse.urlencode({"api": token, "url": original_url})
    request = urllib.request.Request(
        f"{endpoint}?{query}", headers={"User-Agent": "radd-stream/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read(SHORTENER_MAX_RESPONSE_BYTES + 1)
    if len(raw) > SHORTENER_MAX_RESPONSE_BYTES:
        return None
    return _shortened_from_body(raw, original_url)


def shorten_download_url(original_url: str, conn, *, now=None,
                         fetcher=None) -> str | None:
    """The shortened download target for a free user, or None for direct.

    Cache first: a URL this box already shortened costs one SELECT and burns no
    API quota. Otherwise configured networks are tried in rotation order and the
    first success is cached. A shortener that errors, times out or answers a
    shape we do not understand is skipped; when none succeeds the caller falls
    back to the direct URL, so monetization can never break a download."""
    targets = admin_panel.shortener_targets(conn)
    if not targets:
        return None
    ensure_shortened_links(conn)
    cached = cached_shortened_link(conn, original_url)
    if cached:
        return cached
    fetcher = fetcher or call_shortener
    for network, token in rotate_shortener_targets(targets, now=now):
        try:
            shortened = fetcher(network, token, original_url)
        except Exception:      # noqa: BLE001 — a third party must not break downloads
            continue
        if shortened:
            cache_shortened_link(conn, original_url, network, shortened)
            return shortened
    return None


def _bearer_token(headers) -> str:
    raw = str((headers or {}).get("Authorization", "") or "")
    parts = raw.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return ""


def request_is_vip(headers, query_params, *, now=None, secret=None) -> bool:
    """Whether this download request carries a live VIP capability.

    Three forms, all server-verifiable: a sync account whose `vip_until` has not
    passed (`Authorization: Bearer <sync key>`), or a signed pass minted for a
    rewarded-ad flow (`?vip=<pass>` or `?vip_token=<pass>`), or the same signed
    pass in the `X-Radd-Vip-Pass` request header (the embed player sends it
    there so the pass never lands in browser history — the header is only ever
    read on the initial redirector request; a redirect drops it). There is
    deliberately no bare `vip=1`: a boolean a caller can type is not a purchase,
    and trusting it would let every free user skip the operator's shortener by
    editing a URL."""
    token = _bearer_token(headers)
    if token:
        try:
            import accounts
            if accounts.vip_status(accounts.default_db_path(), token,
                                   now=now).get("vip"):
                return True
        except Exception:      # noqa: BLE001 — an unreadable state DB means "free"
            pass
    secret = signing_secret() if secret is None else secret
    header_pass = str((headers or {}).get(redact.VIP_PASS_HEADER, "") or "").strip()
    if header_pass and redact.parse_vip_pass(header_pass, secret, now=now):
        return True
    for key in ("vip", "vip_token"):
        raw = (query_params.get(key) or [""])[0]
        if raw and redact.parse_vip_pass(raw, secret, now=now):
            return True
    return False


#: The bands the free tier does not get once the operator switches the quality
#: gate on (audit critical 5). Everything at 720p and below — including an
#: unspecified print, which `tiers.band_of` deliberately reads as the
#: conservative free band — is free: this gate protects a purchase, not the
#: catalog.
GATED_QUALITY_BANDS = ("1080p", "2160p")


def quality_gate_block_reason(source_id, headers, query_params):
    """The error name this request must be refused with, or None to serve it.

    The 720p free cap was client-only: a signed handle was the whole of what
    the server demanded, so anyone who skipped the app played 1080p/4K without
    paying for it. This is the server's side of the same promise: the release's
    own band (``tiers.band_of`` over the release's quality/codec/size/title
    columns, never a link field) met by the same server-verifiable credentials
    the shortener split already trusts (``request_is_vip``).

    Opt-in by the operator (``feature_quality_gate``, default on since the
    security release) and fail-open: an unreadable settings row answers
    "free". Refusing every premium play because the config could not be read
    is an availability failure, and this boundary protects revenue, not a
    person.
    """
    try:
        with get_db() as conn:
            admin_panel._ensure_monetization(conn)
            cfg = conn.execute(
                "SELECT feature_quality_gate FROM app_remote_config "
                "WHERE id = 1").fetchone()
            if not cfg or not int(cfg["feature_quality_gate"] or 0):
                return None
            src = conn.execute(
                "SELECT r.quality, r.codec, r.size, r.release_title "
                "FROM download_sources s JOIN releases r ON r.id = s.release_id "
                "WHERE s.id = ?", (source_id,)).fetchone()
    except Exception:      # noqa: BLE001 — an unreadable ledger means free tier
        return None
    if not src:
        return None
    band = tiers.band_of(src["quality"], src["codec"], src["size"],
                         src["release_title"])
    if band not in GATED_QUALITY_BANDS:
        return None
    return None if request_is_vip(headers, query_params) \
        else "premium_quality_requires_vip"


def _art_pair(row, base_url: str) -> dict:
    """Poster + backdrops as our own handles, unless the art already sits on a
    public CDN (TMDB and friends name nothing about us).

    The v1 wire keys stay, so the shipped app and the PWA render art exactly as
    before — only the value changes. Empty when the row has no artwork at all."""
    keys = set(row.keys())

    def column(name, default=None):
        return row[name] if name in keys else default

    secret = signing_secret()
    pid = row["id"]
    poster = redact.public_art_value(column("poster_url"), pid, secret, base_url, "poster")
    raw = column("backdrop_urls")
    try:
        items = json.loads(raw) if raw else []
        if isinstance(items, str):
            items = [items]
    except Exception:
        items = [u.strip() for u in str(raw or "").split(",") if u.strip()]
    backdrops = [
        redact.public_art_value(item, pid, secret, base_url, "backdrop", i)
        for i, item in enumerate(items if isinstance(items, list) else [])
        if str(item or "").strip()
    ]
    return {
        "poster_url": poster,
        # TEXT holding a JSON array of URL strings, exactly as stored — the
        # client's parser is unchanged, only the hosts inside it are ours.
        "backdrop_urls": json.dumps(backdrops) if backdrops else None,
    }


def _season_artwork(conn, post_id: int) -> list:
    """Season posters and episode stills for one work, as the app consumes them.

    The rows live in `post_artwork` because a work has one poster but many seasons.
    Only URLs that already sit on a third-party art CDN are emitted: unlike a work
    poster, these are not addressable through `/api/v1/art` (that redirector resolves
    `posts.poster_url`), so a scraped-site image URL is dropped rather than leaked.
    A missing table is an honest empty list — older databases simply have no seasons
    mapped yet."""
    try:
        rows = conn.execute(
            "SELECT kind, season_number, episode_number, url FROM post_artwork "
            "WHERE post_id = ? "
            "ORDER BY season_number, CASE kind WHEN 'season_poster' THEN 0 ELSE 1 END, "
            "episode_number",
            (post_id,),
        ).fetchall()
    except sqlite3.Error:
        return []
    out = []
    for row in rows:
        url = redact.public_image_value(row["url"])
        if url is None:
            continue
        out.append({
            "kind": row["kind"],
            "season": int(row["season_number"] or 0),
            "episode": int(row["episode_number"] or 0),
            "url": url,
        })
    return out


#: `/api/data`'s page size and its ceiling. Measured 2026-10-30 on this catalog
#: (6.4 GB, 150k posts, 1.38 M releases, 3.8 M links): a 50-post page is ~2.5 MB,
#: so 200 is as large a page as this box should serialise in one request. The
#: operator page paginates rather than asking for more; a caller that asks for
#: more is clamped, never refused into an empty answer it must guess about — and
#: the clamp is *reported* (`page.clamped`), so the operator is never shown 200
#: rows and left to assume that was what they asked for.
_LEDGER_PAGE_DEFAULT = 50
_LEDGER_PAGE_CEILING = 200

#: `/api/sitemap`'s ceiling, for the same reason in a smaller file: the sitemap
#: cache is the one operator table whose row count is measured in millions
#: (3.8 M links, and the sitemap family is the same order), and its old reader
#: passed `?limit=` straight into SQL with a bare `int()` — so `?limit=99999999`
#: was an unbounded read on this box and `?limit=abc` was a traceback.
_SITEMAP_ROW_CEILING = 500

#: Which counters may be computed on the request path.
#:
#: `stamp` (default) reads the projection's `cat_projection_meta` row and answers
#: `null` for anything it did not stamp. `full` is the operator's explicit choice
#: to count the ledger live — measured on 2026-10-30 against the production file:
#: `COUNT(*) FROM releases` 112.6 s, `is_18_plus = 1` 93.0 s, `Bollywood|India`
#: 15.2 s, a 3.8 M-link `GROUP BY state` 42.2 s. Those numbers are why the default
#: may not count: one unauthenticated turn of the dashboard used to spend the only
#: core for two minutes.
_LEDGER_STATS_MODES = ("stamp", "full")


def fetch_database_payload(search_query: str = "", full: bool = False,
                           base_url: str = "", limit: int = _LEDGER_PAGE_DEFAULT,
                           page: int = 1, stats: str = "stamp") -> dict:
    """The dashboard/API catalog panel.

    `full` is the operator-only mode (loopback port): raw ledger rows, exactly as
    stored, for healing and audit. Public callers get `redact` views instead —
    and the difference is one flag at the edge, never two copies of the query.

    The read is bounded twice over. Rows: `limit` is clamped to
    `_LEDGER_PAGE_CEILING` and `page` to a sane range, so no caller can ask for the
    whole ledger however it spells the request — and the answer says so: `page`
    always carries `truncated` (rows remain after this page) and `clamped` (the
    requested page size was reduced to the ceiling). An operator looking at a full
    page must be able to tell "this is the ledger" from "this is what one request
    is allowed to be", because the second one mistaken for the first is how an
    audit concludes a table is empty. Counters: `stats="stamp"` (the
    default) reads the projection's recorded numbers and publishes `null` for the
    ones it did not record; only `stats="full"`, an explicit operator act, counts
    the ledger live. Before this, every dashboard load ran five `posts` scans, a
    1.4 M-row `releases` UNION and — with no safe stamp on the file — a 3.8 M-link
    `GROUP BY`: the 2,533,437-byte / 46.6 s answer this endpoint was audited for.
    A `null` is "this box has not measured it", which is a different statement
    from `0`, and the page renders them differently.

    The adult rule on this panel, stated once so the code and the docs stop arguing:
    no public surface ever lists or plays a flagged row; this operator panel may show
    that a flagged row exists and what its flag is; and stream and download deny a
    flagged row on *both* ports. `full` therefore widens visibility, never playability
    — see `/api/v1/stream` and `/api/v1/download`, which call `redact.link_is_adult`
    unconditionally, and `test_redact.AdultDenialOnBothPortsTests`, which proves it
    over real HTTP."""
    try:
        asked = int(limit)
    except (TypeError, ValueError):
        asked = None
    try:
        limit = min(_LEDGER_PAGE_CEILING, max(1, int(limit)))
    except (TypeError, ValueError):
        limit = _LEDGER_PAGE_DEFAULT
    #: True when the caller spelled a page size this box will not serialise. The
    #: route hands the raw parameter down precisely so this can be answered; if it
    #: clamped first, `clamped` could only ever lie.
    clamped = asked is not None and asked != limit
    try:
        page = max(1, int(page))
    except (TypeError, ValueError):
        page = 1
    offset = (page - 1) * limit
    live = str(stats).strip().lower() == "full"
    if not DB_PATH.exists():
        return {"stats": {}, "posts": [],
                "page": {"limit": limit, "page": page, "offset": offset,
                         "returned": 0, "has_more": False, "truncated": False,
                         "clamped": clamped,
                         "ceiling": _LEDGER_PAGE_CEILING}}
    _ensure_schema()

    with get_db() as conn:
        meta = {}
        try:
            meta = dict(conn.execute("SELECT key, value FROM cat_projection_meta").fetchall())
        except Exception:
            pass

        s_count = conn.execute("SELECT COUNT(*) FROM sitemap_cache").fetchone()[0]
        s_vega = conn.execute("SELECT COUNT(*) FROM sitemap_cache WHERE site = 'vegamovies'").fetchone()[0]
        s_rog = conn.execute("SELECT COUNT(*) FROM sitemap_cache WHERE site = 'rogmovies'").fetchone()[0]

        # Counters: stamped by default, counted only when the operator says "full".
        # `live` is the one switch that may start a table scan from this function.
        p_count = p_adult = p_holly = p_bolly = p_anime = None
        page_counts = {}
        r_count = src_count = None
        by_state = None
        resumable_count = 0
        if live:
            p_count = conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
            p_adult = conn.execute("SELECT COUNT(*) FROM posts WHERE is_18_plus = 1").fetchone()[0]
            try:
                # A release may still carry the only attribution an older ledger
                # recorded; counting both tables keeps that site from disappearing
                # from the operator totals just because the v2 projection is newer.
                page_counts = {
                    row[0]: row[1]
                    for row in conn.execute(
                        """
                        SELECT source_site, COUNT(DISTINCT post_id) FROM (
                            SELECT source_site, post_id FROM cat_work_sites
                            UNION ALL
                            SELECT source_site, post_id FROM releases
                            WHERE source_site IS NOT NULL AND source_site != ''
                        )
                        GROUP BY source_site
                        """
                    ).fetchall()
                }
            except Exception:
                try:
                    page_counts = {
                        row[0]: row[1]
                        for row in conn.execute(
                            """
                            SELECT source_site, COUNT(DISTINCT post_id) FROM releases
                            WHERE source_site IS NOT NULL AND source_site != ''
                            GROUP BY source_site
                            """
                        ).fetchall()
                    }
                except Exception:
                    pass
            p_holly = conn.execute("SELECT COUNT(*) FROM posts WHERE industry LIKE '%Hollywood%'").fetchone()[0]
            p_bolly = conn.execute("SELECT COUNT(*) FROM posts WHERE industry LIKE '%Bollywood%' OR country = 'India'").fetchone()[0]
            p_anime = conn.execute("SELECT COUNT(*) FROM posts WHERE is_animated = 1 OR industry = 'Anime'").fetchone()[0]
            r_count = conn.execute("SELECT COUNT(*) FROM releases").fetchone()[0]
            src_count = conn.execute("SELECT COUNT(*) FROM download_sources").fetchone()[0]
        else:
            # A stamp is the ledger as the projection last read it, not a live
            # count — which is the whole point: it costs a row read, not a scan.
            p_count = _meta_count(meta.get("posts"))
            r_count = _meta_count(meta.get("releases"))
            src_count = _meta_count(meta.get("links"))

        if live:
            p_vega = page_counts.get("vegamovies", 0)
            p_rog = page_counts.get("rogmovies", 0)
            p_ssr = page_counts.get("ssrmovies", 0)
            p_kat = page_counts.get("katmoviehd", 0)
            p_7star = page_counts.get("7starhd", 0)
        else:
            # Not stamped, not guessed: the dashboard renders these as "—".
            p_vega = p_rog = p_ssr = p_kat = p_7star = None

        # `active_sources` here used to be the total link count: with
        # `links_by_state = {"unchecked": 3456460}` it told the dashboard that every
        # mirror in the catalog had been knocked on and answered, when nothing had.
        # The link family on this panel is the projection's adult-excluded breakdown,
        # so active/dead/resumable are three views of the same counted set instead of
        # two from the safe stamp and one from the unfiltered rows.
        by_state = _meta_by_state(meta.get("links_by_state_safe"))
        if by_state is not None:
            resumable_count = _meta_count(meta.get("links_resumable_safe")) or 0
        elif live:
            by_state, resumable_count, _ = _ledger_link_breakdown(conn)
        else:
            resumable_count = None
        active_count = int(by_state.get("active", 0) or 0) if by_state is not None else None
        dead_count = int(by_state.get("dead", 0) or 0) if by_state is not None else None

        stats = {
            "sitemap_cached": s_count,
            "sitemap_vega": s_vega,
            "sitemap_rog": s_rog,
            "posts_count": p_count,
            # The operator's own scale: how much of `posts_count` the public surfaces
            # are not allowed to list. Only this panel answers it, and the answer is a
            # count, never a row.
            "posts_adult": p_adult,
            "vega_posts": p_vega,
            "rog_posts": p_rog,
            "ssr_posts": p_ssr,
            "kat_posts": p_kat,
            "star7_posts": p_7star,
            "hollywood_count": p_holly,
            "bollywood_count": p_bolly,
            "anime_count": p_anime,
            "releases_count": r_count,
            "sources_count": src_count,
            "active_sources": active_count,
            "resumable_sources": resumable_count,
            "dead_sources": dead_count,
            # Which of the numbers above this answer measured, so a `null` is read
            # as "not measured" rather than "zero". The stamp is the projection's
            # record of the ledger it last read; `projected_at` says how old it is.
            "stats_source": "live" if live else "stamp",
            "stamped_at": meta.get("projected_at"),
            "unavailable": sorted(
                key for key, value in (
                    ("posts_count", p_count), ("posts_adult", p_adult),
                    ("vega_posts", p_vega), ("rog_posts", p_rog),
                    ("ssr_posts", p_ssr), ("kat_posts", p_kat),
                    ("star7_posts", p_7star), ("hollywood_count", p_holly),
                    ("bollywood_count", p_bolly), ("anime_count", p_anime),
                    ("releases_count", r_count), ("sources_count", src_count),
                    ("active_sources", active_count),
                    ("resumable_sources", resumable_count),
                    ("dead_sources", dead_count),
                ) if value is None),
        }

        # The one surface allowed to *see* a flagged row is the operator's, and it is
        # unreachable from the network twice over: `/api/data` is in
        # OPERATOR_ONLY_ROUTES (this process 404s it on the public port) and nginx
        # never proxies it. Listing the row is what makes the dashboard's
        # `🔞 18+ ADULT` badge true — an audit needs the flag, not the fiction that
        # the catalog holds no adult titles, which is also what `posts_count` above
        # already counted. Playing one is denied on both ports.
        #
        # Denied on both ports is not the same as absent from the panel, and the law
        # is the stricter of the two: the panel must not emit a playable handle for a
        # flagged row at all. See `_withhold_playable`.
        adult_rule = "1=1" if full else redact.adult_clause("posts")
        sql = f"SELECT * FROM posts WHERE {adult_rule}"
        params = []
        if search_query:
            sql += " AND (clean_title LIKE ? OR title LIKE ? OR slug LIKE ? OR industry LIKE ? OR country LIKE ? OR language LIKE ? OR cast_names LIKE ?)"
            p = f"%{search_query}%"
            params = [p, p, p, p, p, p, p]
        # One row past the page decides `has_more` without a COUNT over the table;
        # a COUNT here was the other way this route could spend a minute on I/O.
        sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
        params = list(params) + [limit + 1, offset]
        post_rows = conn.execute(sql, params).fetchall()
        has_more = len(post_rows) > limit
        post_rows = post_rows[:limit]

        posts = []
        for p in post_rows:
            pid = p["id"]
            # Only ever true in `full` mode: the public branch never returns a
            # flagged row in the first place (`adult_clause` excludes it in SQL).
            flagged = bool(p["is_18_plus"])
            rel_rows = conn.execute(
                "SELECT * FROM releases WHERE post_id = ? ORDER BY season ASC, episode ASC, quality DESC, id ASC",
                (pid,),
            ).fetchall()

            releases = []
            for r in rel_rows:
                rid = r["id"]
                src_rows = conn.execute(
                    "SELECT * FROM download_sources WHERE release_id = ? ORDER BY id ASC",
                    (rid,),
                ).fetchall()
                if full:
                    sources = [dict(s) if not flagged else _withhold_playable(s)
                               for s in src_rows]
                else:
                    sources = [link_view(s, base_url) for s in src_rows]

                if full:
                    r_dict = dict(r) if not flagged else _withhold_playable(r)
                else:
                    r_dict = redact.project(r, "release")
                    r_dict["label"] = redact.public_label(r)
                r_dict["sources"] = sources
                releases.append(r_dict)

            if full:
                p_dict = dict(p)
                p_dict["source_pages"] = [
                    dict(row)
                    for row in conn.execute(
                        "SELECT source_site, url, source_title, source_slug, first_seen_at, last_seen_at "
                        "FROM post_sources WHERE post_id = ? ORDER BY source_site, url",
                        (pid,),
                    ).fetchall()
                ]
            else:
                p_dict = redact.project(p, "post_detail")
                p_dict.update(_art_pair(p, base_url))
            p_dict["releases"] = releases
            posts.append(p_dict)

        if not full:
            stats = redact.project(stats, "dashboard_stats")
            # The allowlist is the contract, and `unavailable` names counters: keep
            # it to the counters this view publishes, so a per-site key can never
            # ride out inside a diagnostic list.
            published = redact.VIEWS["dashboard_stats"]
            stats["unavailable"] = [key for key in stats.get("unavailable", [])
                                    if key in published]
        return {
            "stats": stats,
            "posts": posts,
            "page": {"limit": limit, "page": page, "offset": offset,
                     "returned": len(posts), "has_more": has_more,
                     "truncated": has_more, "clamped": clamped,
                     "ceiling": _LEDGER_PAGE_CEILING},
        }


def search_sitemap_api(query: str, site: str = "", limit: int = 50) -> list[dict]:
    """Operator-only: the upstream sitemap index, with its page URLs and sites.

    Served on the loopback port and nowhere else — there is no public reading of
    it that would not be a list of upstream pages.

    The row cap lives here, not only in the route, because this is the function
    that touches SQL: a caller that reached it from anywhere else used to be able
    to hand `?limit=100000000` straight to SQLite and materialise the answer as a
    list of dicts on a box with one vCPU and 11.9 GB of RAM. A non-numeric or
    absent limit falls back to the page default rather than raising.
    """
    try:
        limit = min(_SITEMAP_ROW_CEILING, max(1, int(limit)))
    except (TypeError, ValueError):
        limit = _LEDGER_PAGE_DEFAULT
    words = [w.strip().lower() for w in query.split() if w.strip()]
    with get_db() as conn:
        conditions = []
        params = []
        if words:
            conditions.extend(["slug LIKE ?" for _ in words])
            params.extend([f"%{w}%" for w in words])
        if site and site != "all":
            conditions.append("site = ?")
            params.append(site)

        sql = "SELECT loc, slug, lastmod, scraped, site FROM sitemap_cache"
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY lastmod DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


def generate_m3u_playlist(post_id: int, full: bool = False,
                          base_url: str = "") -> str:
    """VLC / Kodi playlist for one work.

    Public entries are our own ``/api/v1/stream`` handles, so a playlist file
    handed to a friend names no site and no hoster; the player still follows the
    redirect and gets bytes. `full` (loopback port only) keeps today's operator
    listing: hoster name in the title and the raw upstream URL, which is what a
    healer needs to see."""
    with get_db() as conn:
        post = conn.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
        if not post or post["is_18_plus"]:
            return ""

        releases = conn.execute("SELECT * FROM releases WHERE post_id = ? ORDER BY season ASC, episode ASC, quality DESC, id ASC", (post_id,)).fetchall()
        lines = ["#EXTM3U", f"#PLAYLIST:{redact.scrub_text(post['clean_title'])} ({post['year'] or ''})"]

        for r in releases:
            sources = conn.execute("""
                SELECT * FROM download_sources
                WHERE release_id = ? AND (status IS NULL OR status NOT IN
                    ('dead', 'broken', 'gone', 'expired', 'unreachable'))
                ORDER BY is_resumable DESC, id ASC
            """, (r["id"],)).fetchall()
            for s in sources:
                dur = "-1"
                res_tag = " [⚡Resumable]" if s["is_resumable"] else ""
                if full:
                    title = f"{post['clean_title']} - {r['release_title']} [{s['source_name']}]{res_tag}"
                    target = s["final_url"]
                else:
                    label = redact.public_label(r) or ""
                    title = f"{redact.scrub_text(post['clean_title'])} - {label}{res_tag}"
                    handle = redact.mint_token(s["id"], signing_secret())
                    root = (base_url or "").rstrip("/") or "http://localhost:8080"
                    target = f"{root}/api/v1/stream?id={handle}"
                lines.append(f"#EXTINF:{dur},{title}")
                lines.append(target)

        return "\n".join(lines)


#: The escaping core, shipped verbatim inside both page scripts — the dashboard's
#: and the PWA's — because two documents that each carry their own escaper are two
#: escapers that drift, and the drift is invisible until the catalog row with a `<`
#: in its title renders as markup. `Fast_Fetch/test_html_escape_guard.py` reads this
#: constant, requires it inside `DASHBOARD_HTML` and `MOBILE_CLIENT_HTML`, and then
#: requires every markup-bearing template literal in both pages to be an `esc` one.
ESCAPE_CORE_JS = """
    // ── the one place that decides escaping ───────────────────────────────────
    //
    // `esc` is a template tag: every value interpolated through it is escaped by
    // default, and the only way to put markup in is to say so — `raw()` around a
    // fragment that `esc` already built. A page where twelve renderers each remember
    // to call an escaper has twelve chances to forget one, and this page's data
    // comes out of a scraper: a title containing `<` is a normal catalog row, not an
    // attack. So the decision lives here and nowhere else, and
    // Fast_Fetch/test_html_escape_guard.py fails CI when a markup template literal
    // appears that does not use this tag, or when an `on*=` attribute interpolates
    // anything at all — the class of bug where `&#39;` is decoded back into a `'`
    // before the script inside the attribute is parsed, which an escaper cannot
    // prevent and only a data attribute can.
    const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, ch => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[ch]));
    const raw = value => ({ __raddRaw: String(value ?? '') });
    const esc = (strings, ...values) => {
      let out = String(strings[0] ?? '');
      for (let i = 0; i < values.length; i += 1) {
        const value = values[i];
        out += ((value && typeof value === 'object' && '__raddRaw' in value)
          ? value.__raddRaw : escapeHtml(value)) + String(strings[i + 1] ?? '');
      }
      return out;
    };
    // A URL is escaped like text and then checked like a URL, because `javascript:`
    // survives quoting: an escaper's job is delimiters, not schemes.
    const safeHttpUrl = value => {
      try {
        const parsed = new URL(String(value));
        return parsed.protocol === 'http:' || parsed.protocol === 'https:' ? parsed.href : '';
      } catch (_) {
        return '';
      }
    };
    // Ids are numbers or they are nothing, and `num` is what an interpolation is
    // allowed to be when it is not text.
    const num = value => { const n = Number(value); return Number.isFinite(n) ? String(n) : '0'; };
"""


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Fast_Fetch — Database & Site Explorer</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg: #0b0f19;
      --card-bg: #111827;
      --card-border: #1f2937;
      --card-hover: #1e293b;
      --accent: #3b82f6;
      --accent-hover: #2563eb;
      --accent-glow: rgba(59, 130, 246, 0.25);
      --success: #10b981;
      --success-glow: rgba(16, 185, 129, 0.2);
      --warning: #f59e0b;
      --text: #f9fafb;
      --text-muted: #9ca3af;
      --text-dim: #6b7280;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: var(--bg);
      color: var(--text);
      font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif;
      min-height: 100vh;
      padding: 24px 20px 60px;
    }
    .container { max-width: 1320px; margin: 0 auto; }

    /* Header */
    header {
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
      margin-bottom: 24px;
      padding-bottom: 20px;
      border-bottom: 1px solid var(--card-border);
    }
    .logo-area { display: flex; align-items: center; gap: 12px; }
    .logo-badge {
      background: linear-gradient(135deg, #3b82f6, #10b981);
      color: #fff;
      font-weight: 800;
      font-size: 18px;
      padding: 8px 14px;
      border-radius: 10px;
      letter-spacing: 0.5px;
      box-shadow: 0 4px 15px var(--accent-glow);
    }
    .logo-title h1 { font-size: 22px; font-weight: 800; letter-spacing: -0.5px; }
    .logo-title p { font-size: 13px; color: var(--text-muted); }

    /* Navigation Tabs */
    .nav-tabs {
      display: flex;
      gap: 10px;
      margin-bottom: 24px;
      border-bottom: 1px solid var(--card-border);
      padding-bottom: 12px;
    }
    .tab-btn {
      background: transparent;
      border: 1px solid transparent;
      color: var(--text-muted);
      font-size: 14px;
      font-weight: 700;
      padding: 10px 20px;
      border-radius: 8px;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 8px;
      transition: all 0.15s;
    }
    .tab-btn:hover { color: #fff; background: var(--card-bg); }
    .tab-btn.active {
      background: var(--card-bg);
      border-color: var(--card-border);
      color: var(--accent);
      box-shadow: 0 4px 12px rgba(0,0,0,0.2);
    }

    /* Stats Grid */
    .stats-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 14px;
      margin-bottom: 24px;
    }
    .stat-card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 12px;
      padding: 16px 20px;
      display: flex;
      flex-direction: column;
      gap: 4px;
      transition: transform 0.15s ease, border-color 0.15s ease;
    }
    .stat-card:hover { border-color: #374151; transform: translateY(-2px); }
    .stat-label { font-size: 12px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.8px; font-weight: 600; }
    .stat-val { font-size: 26px; font-weight: 800; color: #fff; }

    /* Controls Bar */
    .controls {
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      margin-bottom: 24px;
      align-items: center;
    }
    .search-input {
      flex: 1;
      min-width: 280px;
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      color: var(--text);
      font-size: 15px;
      padding: 12px 18px;
      border-radius: 10px;
      outline: none;
      font-family: inherit;
      transition: border-color 0.2s, box-shadow 0.2s;
    }
    .search-input:focus {
      border-color: var(--accent);
      box-shadow: 0 0 0 3px var(--accent-glow);
    }
    .filter-btn {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      color: var(--text-muted);
      padding: 10px 16px;
      border-radius: 10px;
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
      transition: all 0.15s;
    }
    .filter-btn:hover { color: #fff; border-color: #4b5563; }
    .filter-btn.active {
      background: var(--accent);
      color: #fff;
      border-color: var(--accent);
      box-shadow: 0 4px 12px var(--accent-glow);
    }

    /* Media Cards */
    .media-card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 14px;
      margin-bottom: 20px;
      overflow: hidden;
      box-shadow: 0 8px 24px rgba(0,0,0,0.3);
      transition: border-color 0.2s;
    }
    .media-card:hover { border-color: #374151; }
    .media-header {
      padding: 18px 22px;
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      background: rgba(255, 255, 255, 0.02);
      border-bottom: 1px solid var(--card-border);
    }
    .media-title-group { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
    .media-title { font-size: 18px; font-weight: 700; color: #fff; }
    .media-badge {
      font-size: 11px;
      font-weight: 700;
      padding: 4px 10px;
      border-radius: 6px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }
    .badge-movie { background: #3730a3; color: #c7d2fe; }
    .badge-series { background: #065f46; color: #a7f3d0; }
    .badge-ongoing { background: #854d0e; color: #fef08a; }
    .badge-year { background: #1f2937; color: var(--text-muted); }
    .badge-season { background: #1e3a8a; color: #bfdbfe; font-weight: 700; }
    .badge-18 { background: #7f1d1d; color: #fecaca; border: 1px solid #ef4444; box-shadow: 0 0 10px rgba(239,68,68,0.3); font-weight: 800; }
    .badge-anim { background: #581c87; color: #e9d5ff; border: 1px solid #a855f7; font-weight: 800; }
    .badge-imdb { background: #78350f; color: #fde047; font-weight: 800; border: 1px solid #d97706; }
    .badge-vega { background: #1e1b4b; color: #a5b4fc; border: 1px solid #4f46e5; font-weight: 700; }
    .badge-rog { background: #451a03; color: #fdba74; border: 1px solid #ea580c; font-weight: 700; }
    .badge-ssr { background: #3b0764; color: #d8b4fe; border: 1px solid #9333ea; font-weight: 700; }
    .badge-kat { background: #14532d; color: #86efac; border: 1px solid #22c55e; font-weight: 700; }
    .badge-7star { background: #701a75; color: #f472b6; border: 1px solid #db2777; font-weight: 700; }
    .badge-mm { background: #7c2d12; color: #ffedd5; border: 1px solid #ea580c; font-weight: 700; }
    .badge-10x { background: #831843; color: #fce7f3; border: 1px solid #ec4899; font-weight: 700; }
    .badge-industry { background: #082f49; color: #7dd3fc; border: 1px solid #0284c7; font-weight: 700; }
    .badge-country { background: #052e16; color: #86efac; border: 1px solid #16a34a; font-weight: 700; }
    .badge-lang { background: #2e1065; color: #d8b4fe; border: 1px solid #7e22ce; font-weight: 600; }
    .pill-genre { background: #1e293b; color: #94a3b8; border: 1px solid #334155; font-size: 11px; padding: 2px 7px; border-radius: 4px; font-weight: 600; }
    .pill-resumable { background: #064e3b; color: #6ee7b7; border: 1px solid #059669; font-size: 10px; padding: 2px 6px; border-radius: 4px; font-weight: 700; }
    .source-dead { opacity: 0.7; border-color: #7f1d1d !important; }
    .poster-thumb { width: 50px; height: 72px; object-fit: cover; border-radius: 6px; border: 1px solid #334155; flex-shrink: 0; box-shadow: 0 4px 10px rgba(0,0,0,0.5); }
    .btn-check { background: #1e3a8a; color: #dbeafe; border: 1px solid #3b82f6; padding: 6px 10px; border-radius: 6px; font-size: 12px; font-weight: 600; cursor: pointer; transition: all 0.15s; }
    .btn-check:hover { background: #2563eb; color: #fff; }
    .btn-heal { background: #9a3412; color: #ffedd5; border: 1px solid #ea580c; padding: 6px 10px; border-radius: 6px; font-size: 12px; font-weight: 600; cursor: pointer; transition: all 0.15s; }
    .btn-heal:hover { background: #c2410c; color: #fff; }

    .media-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
    .btn-m3u {
      background: #4338ca;
      color: #e0e7ff;
      border: 1px solid #6366f1;
      padding: 6px 12px;
      border-radius: 6px;
      font-size: 12px;
      font-weight: 600;
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      gap: 4px;
      transition: all 0.15s;
    }
    .btn-m3u:hover { background: #4f46e5; color: #fff; }

    .post-link {
      color: var(--text-dim);
      font-size: 12px;
      text-decoration: none;
      display: flex;
      align-items: center;
      gap: 4px;
      transition: color 0.15s;
    }
    .post-link:hover { color: var(--accent); }

    /* Media Body */
    .media-body { padding: 20px 22px; }

    /* Season Section */
    .season-section { margin-bottom: 24px; }
    .season-section:last-child { margin-bottom: 0; }
    .season-heading {
      font-size: 14px;
      font-weight: 700;
      color: #93c5fd;
      margin-bottom: 12px;
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .season-heading::after {
      content: '';
      flex: 1;
      height: 1px;
      background: #1f2937;
    }

    /* Release Grid */
    .releases-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
      gap: 14px;
    }
    .release-box {
      background: #161f30;
      border: 1px solid #233148;
      border-radius: 10px;
      padding: 14px 16px;
      display: flex;
      flex-direction: column;
      gap: 10px;
      transition: border-color 0.15s, background 0.15s;
    }
    .release-box:hover { border-color: #3b82f6; background: #1a253a; }
    .release-top {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 8px;
    }
    .release-title {
      font-size: 13px;
      font-weight: 600;
      color: #e2e8f0;
      line-height: 1.4;
      flex: 1;
    }
    .pill {
      font-size: 11px;
      font-weight: 700;
      padding: 3px 8px;
      border-radius: 5px;
      white-space: nowrap;
    }
    .pill-480p { background: #334155; color: #94a3b8; }
    .pill-720p { background: #1e3a5f; color: #60a5fa; }
    .pill-1080p { background: #1e293b; color: #38bdf8; border: 1px solid #0284c7; }
    .pill-2160p, .pill-4k { background: #581c87; color: #e9d5ff; border: 1px solid #9333ea; }
    .pill-batch { background: #065f46; color: #6ee7b7; font-weight: 700; }

    .release-meta {
      display: flex;
      gap: 10px;
      font-size: 12px;
      color: var(--text-muted);
      font-weight: 500;
    }

    /* Source Links List */
    .sources-list {
      display: flex;
      flex-direction: column;
      gap: 7px;
      padding-top: 8px;
      border-top: 1px solid #233148;
    }
    .source-item {
      display: flex;
      justify-content: space-between;
      align-items: center;
      background: #0f172a;
      border: 1px solid #1e293b;
      padding: 8px 12px;
      border-radius: 6px;
      gap: 8px;
      font-size: 12px;
    }
    .source-name {
      font-weight: 600;
      color: #94a3b8;
      display: flex;
      align-items: center;
      gap: 6px;
    }
    .source-actions { display: flex; align-items: center; gap: 6px; }
    .btn-action {
      background: #1e293b;
      border: 1px solid #334155;
      color: #cbd5e1;
      padding: 4px 10px;
      border-radius: 5px;
      font-size: 11px;
      font-weight: 600;
      cursor: pointer;
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      gap: 4px;
      transition: all 0.15s;
    }
    .btn-action:hover { background: var(--accent); color: #fff; border-color: var(--accent); }
    .btn-open { background: #064e3b; border-color: #059669; color: #a7f3d0; }
    .btn-open:hover { background: #059669; color: #fff; }

    /* Sitemap Explorer List */
    .sitemap-list {
      display: flex;
      flex-direction: column;
      gap: 10px;
    }
    .sitemap-row {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 10px;
      padding: 14px 18px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
      transition: border-color 0.15s;
    }
    .sitemap-row:hover { border-color: #3b82f6; }
    .sitemap-info { flex: 1; }
    .sitemap-title { font-size: 14px; font-weight: 700; color: #fff; margin-bottom: 4px; }
    .sitemap-meta { font-size: 12px; color: var(--text-dim); display: flex; gap: 12px; }
    .btn-fetch {
      background: linear-gradient(135deg, #2563eb, #10b981);
      border: none;
      color: #fff;
      padding: 8px 16px;
      border-radius: 8px;
      font-size: 12px;
      font-weight: 700;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      box-shadow: 0 4px 12px var(--accent-glow);
      transition: transform 0.15s, opacity 0.15s;
    }
    .btn-fetch:hover { transform: scale(1.03); }
    .btn-fetch:disabled { opacity: 0.6; cursor: wait; }

    /* Toast */
    .toast {
      position: fixed;
      bottom: 24px;
      right: 24px;
      background: #10b981;
      color: #fff;
      padding: 10px 18px;
      border-radius: 8px;
      font-size: 13px;
      font-weight: 600;
      box-shadow: 0 4px 15px rgba(16, 185, 129, 0.4);
      display: none;
      animation: fadeIn 0.2s;
      z-index: 9999;
    }
    @keyframes fadeIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }

    /* Video Player Modal */
    .modal-overlay {
      position: fixed; inset: 0; background: rgba(0,0,0,0.85); z-index: 99999;
      display: flex; align-items: center; justify-content: center; padding: 16px;
    }
    .modal-content {
      background: #0f172a; border: 1px solid #334155; border-radius: 14px;
      width: 100%; max-width: 840px; padding: 20px; box-shadow: 0 25px 50px -12px rgba(0,0,0,0.7);
    }
    .modal-header {
      display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;
    }
    .modal-close {
      background: none; border: none; color: #94a3b8; font-size: 22px; cursor: pointer; padding: 4px 8px; line-height: 1;
    }
    .modal-close:hover { color: #fff; }

    /* Empty state */
    .empty-state {
      text-align: center;
      padding: 60px 20px;
      color: var(--text-dim);
    }
    .empty-state h3 { font-size: 18px; color: var(--text-muted); margin-bottom: 8px; }
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div class="logo-area">
        <div class="logo-badge">⚡ FAST_FETCH</div>
        <div class="logo-title">
          <h1>Direct Link Database Explorer</h1>
          <p>Instant sitemap search, season & episode manager, and direct CDN resolver</p>
        </div>
      </div>
      <div style="display: flex; gap: 8px; flex-wrap: wrap;">
        <a href="/client" class="filter-btn" style="text-decoration:none; display:inline-flex; align-items:center; gap:6px; background:#2563eb; color:white; border-color:#3b82f6;">📱 Mobile App</a>
        <button class="filter-btn" id="btn-global-check" onclick="runGlobalHealthCheck()">🩺 Check All Links</button>
        <button class="filter-btn" onclick="fetchData()">🔄 Refresh</button>
      </div>
    </header>

    <div class="stats-grid">
      <div class="stat-card">
        <div class="stat-label">Sitemap URLs Cached</div>
        <div class="stat-val" id="stat-sitemap" style="color: #60a5fa;">0</div>
        <div style="font-size: 11px; color: var(--text-dim);" id="stat-sitemap-sub">Vegamovies &amp; RogMovies</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Indexed Media Posts</div>
        <div class="stat-val" id="stat-posts">0</div>
        <div style="font-size: 11px; color: var(--text-dim);" id="stat-posts-sub">Hollywood &amp; Bollywood</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Release Variants</div>
        <div class="stat-val" id="stat-releases">0</div>
        <div style="font-size: 11px; color: var(--text-dim);">480p, 720p, 1080p, 4K &amp; Batches</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Resolved Direct Links</div>
        <div class="stat-val" id="stat-sources" style="color: #38bdf8;">0</div>
        <div style="font-size: 11px; color: var(--text-dim);">CDN, FastDL, Pixeldrain, HubCloud</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">🟢 Verified Active</div>
        <div class="stat-val" id="stat-active" style="color: #10b981;">0</div>
        <div style="font-size: 11px; color: var(--text-dim);">Live 200 OK CDN streams</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">⚡ Resumable (Range 206)</div>
        <div class="stat-val" id="stat-resumable" style="color: #a7f3d0;">0</div>
        <div style="font-size: 11px; color: var(--text-dim);">Fast seek &amp; multi-part DL</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">🔴 Dead / Expired</div>
        <div class="stat-val" id="stat-dead" style="color: #f87171;">0</div>
        <div style="font-size: 11px; color: var(--text-dim);">Self-healing candidates</div>
      </div>
    </div>

    <div id="stats-note" style="margin: 8px 2px 0; font-size: 11px; color: var(--text-dim); display: flex; gap: 10px; align-items: center; flex-wrap: wrap;">
      <span id="stats-source">Counters: reading the projection stamp…</span>
      <button class="filter-btn" id="btn-stats-live" onclick="fetchData(null, currentPage, 'full')">🧮 Count live (slow)</button>
    </div>

    <div class="nav-tabs">
      <button class="tab-btn active" id="tab-db-btn" onclick="switchMainTab('db')">
        💾 Indexed Database Releases
      </button>
      <button class="tab-btn" id="tab-site-btn" onclick="switchMainTab('site')">
        🌐 Multi-Site Catalog Explorer (16,000+ Titles)
      </button>
    </div>

    <!-- TAB 1: DB RELEASES -->
    <div id="section-db">
      <div class="controls">
        <input type="text" id="search-box" class="search-input" placeholder="🔍 Search saved titles, qualities (1080p, 4K), audio, episodes, Hollywood, Bollywood..." oninput="handleSearch()">
        <button class="filter-btn active" onclick="setFilter('all', this)">All</button>
        <button class="filter-btn" onclick="setFilter('multimovies', this)">🍿 MultiMovies</button>
        <button class="filter-btn" onclick="setFilter('10xflix', this)">💥 10xflix / WWE</button>
        <button class="filter-btn" onclick="setFilter('katmoviehd', this)">🟢 KatMovieHD</button>
        <button class="filter-btn" onclick="setFilter('ssrmovies', this)">🟣 SSRMovies</button>
        <button class="filter-btn" onclick="setFilter('7starhd', this)">⭐ 7StarHD</button>
        <button class="filter-btn" onclick="setFilter('vegamovies', this)">🔵 Vegamovies</button>
        <button class="filter-btn" onclick="setFilter('rogmovies', this)">🟠 RogMovies</button>
        <button class="filter-btn" onclick="setFilter('hollywood', this)">🎬 Hollywood</button>
        <button class="filter-btn" onclick="setFilter('bollywood', this)">🇮🇳 Bollywood</button>
        <button class="filter-btn" onclick="setFilter('anime', this)">🎨 Anime</button>
        <button class="filter-btn" onclick="setFilter('movie', this)">🍿 Movies</button>
        <button class="filter-btn" onclick="setFilter('series', this)">📺 Series</button>
      </div>
      <div id="posts-container">
        <div class="empty-state">
          <h3>Loading database records...</h3>
        </div>
      </div>
      <div id="posts-pager" style="display: flex; gap: 8px; align-items: center; justify-content: center; padding: 16px 0; flex-wrap: wrap;"></div>
    </div>

    <!-- TAB 2: SITEMAP EXPLORER -->
    <div id="section-site" style="display: none;">
      <div class="controls">
        <input type="text" id="sitemap-search-box" class="search-input" placeholder="🔍 Search any movie, anime, or series across all 16,000+ sitemapped posts..." oninput="handleSitemapSearch()">
        <div style="display: flex; gap: 8px; flex-wrap: wrap;">
          <button class="filter-btn active" id="btn-sitemap-site-all" onclick="setSitemapSite('all', this)">🌐 All Sites</button>
          <button class="filter-btn" id="btn-sitemap-site-mm" onclick="setSitemapSite('multimovies', this)">🍿 MultiMovies</button>
          <button class="filter-btn" id="btn-sitemap-site-10x" onclick="setSitemapSite('10xflix', this)">💥 10xflix</button>
          <button class="filter-btn" id="btn-sitemap-site-kat" onclick="setSitemapSite('katmoviehd', this)">🟢 KatMovieHD</button>
          <button class="filter-btn" id="btn-sitemap-site-ssr" onclick="setSitemapSite('ssrmovies', this)">🟣 SSRMovies</button>
          <button class="filter-btn" id="btn-sitemap-site-7star" onclick="setSitemapSite('7starhd', this)">⭐ 7StarHD</button>
          <button class="filter-btn" id="btn-sitemap-site-vega" onclick="setSitemapSite('vegamovies', this)">🔵 Vegamovies</button>
          <button class="filter-btn" id="btn-sitemap-site-rog" onclick="setSitemapSite('rogmovies', this)">🟠 RogMovies</button>
        </div>
        <span style="font-size: 13px; color: var(--text-dim);" id="sitemap-count-indicator">Showing latest posts</span>
      </div>
      <div id="sitemap-container">
        <div class="empty-state">
          <h3>Search the entire site catalog...</h3>
        </div>
      </div>
    </div>
  </div>

  <div id="toast" class="toast">Link copied to clipboard!</div>

  <script>
""" + ESCAPE_CORE_JS + """    const API_BASE = window.location.pathname.endsWith('/') ? window.location.pathname.slice(0, -1) : window.location.pathname;
    // One delegated handler for every button that carries data, and the reason it
    // exists: `onclick="viewInDb('${r.slug}')"` puts a scraped value inside a JS
    // string inside an HTML attribute, which is a context no escaper can make safe —
    // the browser decodes `&#39;` back into a `'` before it parses the script, so
    // escaping the quote is exactly as broken as not escaping it. A data attribute
    // has no parser to fool: it is text, escaped like text, read back with
    // `dataset` after `Number()` when it is meant to be an id.
    const ACTIONS = {
      'goto-page': el => gotoPage(Number(el.dataset.value)),
      'view-in-db': el => viewInDb(el.dataset.value),
      'fetch-on-demand': el => fetchPostOnDemand(el.dataset.loc, el.dataset.value),
      'check-health': el => checkHealthPost(Number(el.dataset.value)),
      'heal-post': el => healPost(Number(el.dataset.value)),
      'play-jit': el => openStreamPlayer(Number(el.dataset.id), el.dataset.name, el.dataset.title),
      'copy-url': el => copyToClipboard(el.dataset.value),
    };
    document.addEventListener('click', event => {
      const trigger = event.target.closest('[data-action]');
      if (!trigger) return;
      const handler = Object.prototype.hasOwnProperty.call(ACTIONS, trigger.dataset.action)
        ? ACTIONS[trigger.dataset.action] : null;
      if (handler) handler(trigger);
    });
    let dbData = { stats: {}, posts: [] };
    let currentFilter = 'all';
    let currentMainTab = 'db';
    let currentSitemapSite = 'all';
    let sitemapSearchTimer = null;
    let currentQuery = '';
    let currentPage = 1;
    let currentStats = 'stamp';

    function switchMainTab(tab) {
      currentMainTab = tab;
      document.getElementById('tab-db-btn').classList.toggle('active', tab === 'db');
      document.getElementById('tab-site-btn').classList.toggle('active', tab === 'site');
      document.getElementById('section-db').style.display = tab === 'db' ? 'block' : 'none';
      document.getElementById('section-site').style.display = tab === 'site' ? 'block' : 'none';
      if (tab === 'site') {
        fetchSitemapList();
      }
    }

    function setSitemapSite(site, el) {
      currentSitemapSite = site;
      document.querySelectorAll('#section-site .filter-btn').forEach(b => b.classList.remove('active'));
      el.classList.add('active');
      const q = document.getElementById('sitemap-search-box').value.trim();
      fetchSitemapList(q);
    }

    async function fetchData(query, page, statsMode) {
      // The endpoint is paginated and its counters are stamped; asking for more
      // than 200 rows or a live count is an explicit choice made here, never a
      // side effect of typing in the search box.
      if (query !== undefined && query !== null) currentQuery = query;
      if (page !== undefined && page !== null) currentPage = Math.max(1, page);
      if (statsMode) currentStats = statsMode;
      try {
        const params = new URLSearchParams();
        if (currentQuery) params.set('q', currentQuery);
        params.set('limit', '50');
        params.set('page', String(currentPage));
        if (currentStats === 'full') params.set('stats', 'full');
        const res = await fetch(API_BASE + '/api/data?' + params.toString());
        dbData = await res.json();
        renderStats();
        renderPosts();
        renderPager();
      } catch (err) {
        console.error(err);
      }
    }

    function renderPager() {
      const box = document.getElementById('posts-pager');
      if (!box) return;
      const p = dbData.page || {};
      if (!p.limit) { box.innerHTML = ''; return; }
      box.innerHTML = esc`
        <button class="filter-btn" data-action="goto-page" data-value="${num(p.page - 1)}"${raw(p.page <= 1 ? ' disabled' : '')}>← Prev</button>
        <span style="font-size:12px;color:var(--text-dim)">page ${num(p.page)} · ${num(p.returned)} rows${raw(p.has_more ? ' · more' : ' · end')} · max ${num(p.ceiling)}/page${raw(p.clamped ? ' · <b style="color:var(--warn,#f5a623)">CLAMPED</b>' : '')}</span>
        <button class="filter-btn" data-action="goto-page" data-value="${num(p.page + 1)}"${raw(p.has_more ? '' : ' disabled')}>Next →</button>`;
    }

    function gotoPage(n) {
      if (n < 1) return;
      fetchData(null, n);
    }

    async function runGlobalHealthCheck() {
      const btn = document.getElementById('btn-global-check');
      if (btn) {
        btn.disabled = true;
        btn.innerText = '⏳ Probing All Links...';
      }
      showToast('🩺 Running health diagnostic on all links in database...');
      try {
        const res = await fetch(API_BASE + '/api/health-check');
        const data = await res.json();
        if (data.success) {
          showToast('✓ Probed ' + data.count + ' links across database!');
          await fetchData(document.getElementById('search-box').value.trim());
        } else {
          alert('Health check error: ' + (data.error || 'Unknown error'));
        }
      } catch (err) {
        alert('Health check error: ' + err.message);
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.innerText = '🩺 Check All Links';
        }
      }
    }

    async function fetchSitemapList(query = '') {
      const container = document.getElementById('sitemap-container');
      container.innerHTML = `<div class="empty-state"><h3>Searching site catalog...</h3></div>`;
      try {
        const url = `${API_BASE}/api/sitemap?q=${encodeURIComponent(query)}&site=${encodeURIComponent(currentSitemapSite)}`;
        const res = await fetch(url);
        const rows = await res.json();
        renderSitemapRows(rows);
      } catch (err) {
        container.innerHTML = `<div class="empty-state"><h3>Error searching sitemap</h3></div>`;
      }
    }

    function renderSitemapRows(rows) {
      const container = document.getElementById('sitemap-container');
      document.getElementById('sitemap-count-indicator').innerText = `Found ${rows.length} posts`;

      if (!rows || rows.length === 0) {
        container.innerHTML = `
          <div class="empty-state">
            <h3>No matching titles found in sitemap</h3>
          </div>
        `;
        return;
      }

      let html = '<div class="sitemap-list">';
      for (const r of rows) {
        const isScraped = r.scraped === 1;
        const siteLabels = {
          rogmovies: ['ROGMOVIES', 'badge-rog'], ssrmovies: ['SSRMOVIES', 'badge-ssr'],
          katmoviehd: ['KATMOVIEHD', 'badge-kat'], '7starhd': ['7STARHD', 'badge-7star'],
          multimovies: ['MULTIMOVIES', 'badge-mm'], '10xflix': ['10XFLIX', 'badge-10x'],
        };
        const labeled = siteLabels[String(r.site)] || ['VEGAMOVIES', 'badge-vega'];
        const siteTag = raw(esc`<span class="media-badge ${labeled[1]}" style="margin-right: 8px;">${labeled[0]}</span>`);
        const slug = String(r.slug ?? '');
        const loc = safeHttpUrl(r.loc);
        const lastmod = String(r.lastmod ?? '');
        const btnHtml = isScraped
          ? esc`<button class="btn-action" data-action="view-in-db" data-value="${slug}">✓ View in DB</button>`
          : esc`<button class="btn-fetch" id="btn-fetch-${slug}" data-action="fetch-on-demand" data-value="${slug}" data-loc="${loc}">⚡ Resolve Direct Links</button>`;

        html += esc`
          <div class="sitemap-row">
            <div class="sitemap-info">
              <div class="sitemap-title">${siteTag}${slug}</div>
              <div class="sitemap-meta">
                <span>📅 ${lastmod.split('T')[0] || lastmod}</span>
                <a href="${loc}" target="_blank" rel="noopener noreferrer" class="post-link">Original Page ↗</a>
              </div>
            </div>
            <div>${raw(btnHtml)}</div>
          </div>
        `;
      }
      html += '</div>';
      container.innerHTML = html;
    }

    async function fetchPostOnDemand(url, slug) {
      const btn = document.getElementById(`btn-fetch-${slug}`);
      if (btn) {
        btn.disabled = true;
        btn.innerText = '⏳ Resolving Links...';
      }
      try {
        const res = await fetch(API_BASE + '/api/fetch?url=' + encodeURIComponent(url));
        const resData = await res.json();
        if (resData.success) {
          showToast('✓ Successfully resolved and saved to database!');
          await fetchData();
          switchMainTab('db');
          document.getElementById('search-box').value = resData.clean_title || slug;
          handleSearch();
        } else {
          alert('Failed to resolve: ' + (resData.error || 'Unknown error'));
          if (btn) { btn.disabled = false; btn.innerText = '⚡ Resolve Direct Links'; }
        }
      } catch (err) {
        alert('Error: ' + err.message);
        if (btn) { btn.disabled = false; btn.innerText = '⚡ Resolve Direct Links'; }
      }
    }

    function viewInDb(slug) {
      switchMainTab('db');
      document.getElementById('search-box').value = slug;
      handleSearch();
    }

    function handleSitemapSearch() {
      clearTimeout(sitemapSearchTimer);
      const q = document.getElementById('sitemap-search-box').value.trim();
      sitemapSearchTimer = setTimeout(() => {
        fetchSitemapList(q);
      }, 250);
    }

    function renderStats() {
      const s = dbData.stats || {};
      // `null` is "not measured", not "zero": an unstamped catalog must not read
      // as a catalog with nothing in it.
      const num = v => (v === null || v === undefined) ? '—' : Number(v).toLocaleString();
      document.getElementById('stat-posts').innerText = num(s.posts_count);
      if (document.getElementById('stat-posts-sub')) {
        document.getElementById('stat-posts-sub').innerText = `🎬 ${num(s.hollywood_count)} Holly · 🇮🇳 ${num(s.bollywood_count)} Bolly · 🎨 ${num(s.anime_count)} Anime`;
      }
      document.getElementById('stat-releases').innerText = num(s.releases_count);
      document.getElementById('stat-sources').innerText = num(s.sources_count);
      document.getElementById('stat-sitemap').innerText = num(s.sitemap_cached);
      if (document.getElementById('stat-sitemap-sub')) {
        document.getElementById('stat-sitemap-sub').innerText = `Vega: ${num(s.sitemap_vega)} · Rog: ${num(s.sitemap_rog)}`;
      }
      if (document.getElementById('stat-active')) {
        document.getElementById('stat-active').innerText = num(s.active_sources);
      }
      if (document.getElementById('stat-resumable')) {
        document.getElementById('stat-resumable').innerText = num(s.resumable_sources);
      }
      if (document.getElementById('stat-dead')) {
        document.getElementById('stat-dead').innerText = num(s.dead_sources);
      }
      const note = document.getElementById('stats-source');
      if (note) {
        const when = s.stamped_at ? new Date(Number(s.stamped_at) * 1000).toLocaleString() : '';
        if (s.stats_source === 'live') {
          note.innerText = 'Counters: counted live just now';
        } else if (s.posts_count === undefined) {
          note.innerText = 'Counters: —';
        } else {
          note.innerText = 'Counters: projection stamp' + (when ? ' from ' + when : (s.stamped_at === null ? ' — never stamped' : ''));
        }
        const missing = (s.unavailable || []).length;
        if (missing) note.innerText += ' · ' + missing + ' key(s) need "Count live"';
      }
    }

    function setFilter(type, el) {
      currentFilter = type;
      document.querySelectorAll('#section-db .filter-btn').forEach(b => b.classList.remove('active'));
      el.classList.add('active');
      renderPosts();
    }

    function handleSearch() {
      const q = document.getElementById('search-box').value.trim();
      // A search starts a new page 1 and drops back to stamped counters — a live
      // count per keystroke would be one full scan per character.
      fetchData(q, 1, 'stamp');
    }

    function copyToClipboard(text) {
      navigator.clipboard.writeText(text).then(() => {
        showToast('Link copied to clipboard!');
      });
    }

    function showToast(msg) {
      const t = document.getElementById('toast');
      t.innerText = msg;
      t.style.display = 'block';
      setTimeout(() => { t.style.display = 'none'; }, 2200);
    }

    async function checkHealthPost(postId) {
      showToast('🩺 Probing links for post #' + postId + '...');
      try {
        const res = await fetch(API_BASE + '/api/health-check?id=' + postId);
        const data = await res.json();
        if (data.success) {
          showToast('✓ Link health probe complete (' + data.count + ' checked)');
          fetchData(document.getElementById('search-box').value.trim());
        } else {
          alert('Health check error: ' + (data.error || 'Unknown error'));
        }
      } catch (err) {
        alert('Health check error: ' + err.message);
      }
    }

    async function healPost(postId) {
      showToast('🔄 Auto-healing links for post #' + postId + '...');
      try {
        const res = await fetch(API_BASE + '/api/heal?id=' + postId);
        const data = await res.json();
        if (data.success) {
          showToast('✓ Auto-healed! Refreshed: ' + data.healed + ' link(s)');
          fetchData(document.getElementById('search-box').value.trim());
        } else {
          alert('Auto-heal error: ' + (data.error || 'Unknown error'));
        }
      } catch (err) {
        alert('Auto-heal error: ' + err.message);
      }
    }

    function formatBytes(bytes) {
      if (!bytes || bytes <= 0) return '';
      const gb = bytes / (1024 * 1024 * 1024);
      if (gb >= 1.0) return gb.toFixed(2) + ' GB';
      const mb = bytes / (1024 * 1024);
      return mb.toFixed(1) + ' MB';
    }

    function getCountryFlag(country) {
      if (!country) return '';
      const c = country.toLowerCase();
      if (c.includes('india')) return '🇮🇳 India';
      if (c.includes('usa') || c.includes('united states')) return '🇺🇸 USA';
      if (c.includes('japan')) return '🇯🇵 Japan';
      if (c.includes('korea')) return '🇰🇷 S.Korea';
      if (c.includes('china')) return '🇨🇳 China';
      if (c.includes('uk') || c.includes('united kingdom')) return '🇬🇧 UK';
      return '📍 ' + country;
    }

    function renderPosts() {
      const container = document.getElementById('posts-container');
      let posts = dbData.posts || [];
      const postHasSite = (post, site) =>
        post.source_site === site ||
        (post.source_pages || []).some(source => source.source_site === site) ||
        (post.releases || []).some(release => release.source_site === site);

      if (currentFilter === 'movie') {
        posts = posts.filter(p => p.content_type === 'movie');
      } else if (currentFilter === 'series') {
        posts = posts.filter(p => p.content_type !== 'movie');
      } else if (currentFilter === 'anime') {
        posts = posts.filter(p => p.is_animated === 1 || (p.industry && p.industry.toLowerCase().includes('anime')));
      } else if (currentFilter === 'katmoviehd') {
        posts = posts.filter(p => postHasSite(p, 'katmoviehd'));
      } else if (currentFilter === 'ssrmovies') {
        posts = posts.filter(p => postHasSite(p, 'ssrmovies'));
      } else if (currentFilter === '7starhd') {
        posts = posts.filter(p => postHasSite(p, '7starhd'));
      } else if (currentFilter === 'multimovies') {
        posts = posts.filter(p => postHasSite(p, 'multimovies'));
      } else if (currentFilter === '10xflix') {
        posts = posts.filter(p => postHasSite(p, '10xflix'));
      } else if (currentFilter === 'vegamovies') {
        posts = posts.filter(p => postHasSite(p, 'vegamovies'));
      } else if (currentFilter === 'rogmovies') {
        posts = posts.filter(p => postHasSite(p, 'rogmovies'));
      } else if (currentFilter === 'hollywood') {
        posts = posts.filter(p => (p.industry && p.industry.toLowerCase().includes('hollywood')));
      } else if (currentFilter === 'bollywood') {
        posts = posts.filter(p => (p.industry && (p.industry.toLowerCase().includes('bollywood') || p.industry.toLowerCase().includes('tollywood') || p.industry.toLowerCase().includes('gujarati') || p.industry.toLowerCase().includes('punjabi') || p.industry.toLowerCase().includes('south'))) || p.country === 'India');
      }

      if (posts.length === 0) {
        container.innerHTML = `
          <div class="empty-state">
            <h3>No matching media found in database</h3>
            <p>Use the 'Multi-Site Catalog Explorer' tab to find and index any of the 16,000+ titles.</p>
          </div>
        `;
        return;
      }

      let html = '';
      for (const p of posts) {
        const badgeClass = p.content_type === 'movie' ? 'badge-movie' : (p.content_type === 'ongoing_season' ? 'badge-ongoing' : 'badge-series');
        const typeLabel = (p.content_type || 'series').replace('_', ' ').toUpperCase();

        const siteBadgeClasses = {
          vegamovies: 'badge-vega', rogmovies: 'badge-rog', ssrmovies: 'badge-ssr',
          katmoviehd: 'badge-kat', '7starhd': 'badge-7star', multimovies: 'badge-mm',
          '10xflix': 'badge-10x'
        };
        const sourceSites = [...new Set([
          p.source_site,
          ...(p.source_pages || []).map(source => source.source_site),
          ...(p.releases || []).map(release => release.source_site)
        ].filter(Boolean).map(site => String(site).toLowerCase()))];
        const siteBadges = raw(sourceSites.map(site =>
          esc`<span class="media-badge ${siteBadgeClasses[site] || 'badge-vega'}">${String(site).toUpperCase()}</span>`
        ).join(''));
        const sourcePageLinks = raw((p.source_pages || []).map(source => {
          const href = safeHttpUrl(source.url);
          if (!href) return '';
          return esc`<a href="${href}" target="_blank" rel="noopener noreferrer">${source.source_site || 'Site'} ↗</a>`;
        }).filter(Boolean).join(' <span aria-hidden="true">·</span> '));
        const sourcePagesHtml = sourcePageLinks
          ? raw(esc`<div style="margin:8px 0 0 58px;font-size:12px;color:var(--text-dim)">Indexed pages: ${sourcePageLinks}</div>`)
          : '';
        const originalPageHref = safeHttpUrl(p.url);
        const originalPageLink = originalPageHref
          ? raw(esc`<a href="${originalPageHref}" target="_blank" rel="noopener noreferrer" class="post-link">First-seen page ↗</a>`)
          : '';

        const indBadge = p.industry ? raw(esc`<span class="media-badge badge-industry">${p.industry}</span>`) : '';
        const cntBadge = p.country ? raw(esc`<span class="media-badge badge-country">${getCountryFlag(p.country)}</span>`) : '';
        const langBadge = p.language ? raw(esc`<span class="media-badge badge-lang">🗣️ ${p.language}</span>`) : '';

        const seasonsMap = {};
        for (const r of (p.releases || [])) {
          const sKey = r.season || 'Standard Releases';
          if (!seasonsMap[sKey]) seasonsMap[sKey] = [];
          seasonsMap[sKey].push(r);
        }

        let genresList = [];
        if (p.genres) {
          try {
            genresList = JSON.parse(p.genres);
          } catch(e) {
            genresList = [p.genres];
          }
        }
        const genresHtml = raw(genresList.map(g => esc`<span class="pill-genre">${g}</span>`).join(' '));

        const posterHref = safeHttpUrl(p.poster_url);
        const posterImgHtml = posterHref
          ? raw(esc`<img src="${posterHref}" class="poster-thumb" alt="${p.clean_title}" loading="lazy" onerror="this.style.display='none'">`)
          : '';

        html += esc`
          <div class="media-card">
            <div class="media-header">
              <div class="media-title-group">
                ${posterImgHtml}
                <div>
                  <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 6px;">
                    ${siteBadges}
                    <span class="media-badge ${badgeClass}">${typeLabel}</span>
                    <span class="media-title">${p.clean_title}</span>
                    ${raw(p.year ? esc`<span class="media-badge badge-year">${p.year}</span>` : '')}
                    ${raw(p.seasons ? esc`<span class="media-badge badge-season">${p.seasons}</span>` : '')}
                    ${raw(p.is_18_plus ? '<span class="media-badge badge-18">🔞 18+ ADULT</span>' : '')}
                    ${raw(p.is_animated ? '<span class="media-badge badge-anim">🎨 ANIME</span>' : '')}
                    ${indBadge}
                    ${cntBadge}
                    ${langBadge}
                    ${raw(p.imdb_rating ? esc`<span class="media-badge badge-imdb">⭐ ${p.imdb_rating} IMDb</span>` : '')}
                  </div>
                  ${raw(genresHtml ? esc`<div style="display: flex; gap: 6px; flex-wrap: wrap;">${genresHtml}</div>` : '')}
                </div>
              </div>
              <div class="media-actions">
                <button class="btn-check" data-action="check-health" data-value="${num(p.id)}">🩺 Probe Links</button>
                <button class="btn-heal" data-action="heal-post" data-value="${num(p.id)}">🔄 Auto-Heal</button>
                ${raw(p.is_18_plus
                  ? '<span class="media-badge badge-18" title="The endpoints refuse this work on both ports and the ledger view publishes no upstream URL for it">🔞 no playlist</span>'
                  : esc`<a href="/api/m3u?id=${num(p.id)}" class="btn-m3u" download="${p.slug}.m3u">📺 VLC Playlist</a>`)}
                ${originalPageLink}
              </div>
            </div>
            ${sourcePagesHtml}
            <div class="media-body">
        `;

        for (const [seasonName, releases] of Object.entries(seasonsMap)) {
          html += esc`
            <div class="season-section">
              <div class="season-heading">${seasonName} (${releases.length} options)</div>
              <div class="releases-grid">
          `;

          for (const r of releases) {
            const qClass = 'pill-' + (r.quality || '720p').toLowerCase();
            const isBatch = r.episode === 'Batch';
            const epBadge = r.episode ? raw(esc`<span class="pill ${isBatch ? 'pill-batch' : 'pill-720p'}">${r.episode}</span>`) : '';
            const rSiteBadge = r.source_site ? raw(esc`<span class="pill" style="background:#0f172a; color:#38bdf8; border:1px solid #0284c7; font-size:10px;">${String(r.source_site).toUpperCase()}</span>`) : '';

            html += esc`
              <div class="release-box">
                <div class="release-top">
                  <span class="release-title">${r.release_title}</span>
                  <div style="display: flex; gap: 4px; align-items: center; flex-wrap: wrap;">
                    ${rSiteBadge}
                    ${epBadge}
                    <span class="pill ${qClass}">${(r.quality || 'HD').toUpperCase()}</span>
                  </div>
                </div>
                <div class="release-meta">
                  ${raw(r.size ? esc`<span>📦 ${r.size}</span>` : '')}
                  ${raw(r.languages ? esc`<span>🌐 ${r.languages}</span>` : '')}
                  ${raw(r.codec ? esc`<span>🎞️ ${r.codec}</span>` : '')}
                </div>
                <div class="sources-list">
            `;

            for (const s of (r.sources || [])) {
              const isTemp = s.is_temporary ? '⏳' : '';
              const isDead = s.status === 'dead' || s.status === 'expired';
              const isActive = s.status === 'active';
              const statusDot = isActive ? '🟢' : (isDead ? '🔴' : '⚪');
              const statusTooltip = s.http_status ? `HTTP ${s.http_status} (${s.status})` : s.status;
              const resumableBadge = s.is_resumable === 1
                ? raw('<span class="pill-resumable" title="HTTP Range 206 supported: Resume, Fast seek, IDM/aria2 multi-part acceleration">⚡ Resumable</span>')
                : '';
              const sizeStr = s.file_size_bytes ? raw(esc`<span style="font-size: 11px; color: var(--text-dim);">${formatBytes(s.file_size_bytes)}</span>`) : '';
              // A flagged work's sources arrive with no URL to copy and no id to
              // stream — `_withhold_playable` removed them server-side, and this
              // renders the refusal instead of a button that would call it.
              const withheld = s.playback_withheld
                ? raw(esc`<span class="pill-resumable" title="Stored for the audit, withheld from the panel">${s.playback_withheld}</span>`)
                : raw(esc`<button class="btn-action" style="background:#2563eb; color:white; border-color:#3b82f6;" data-action="play-jit" data-id="${num(s.id)}" data-name="${s.source_name || 'Direct Stream'}" data-title="${p.clean_title || 'Media Stream'}">▶ Play JIT</button>
                    <button class="btn-action" data-action="copy-url" data-value="${s.final_url}">📋 Copy Direct URL</button>
                    <a href="/api/v1/stream?id=${num(s.id)}&redirect=1" target="_blank" rel="noopener noreferrer" class="btn-action btn-open" title="Instant Live JIT Stream with 302 Redirect">⚡ Stream / DL</a>`);

              html += esc`
                <div class="source-item ${isDead ? 'source-dead' : ''}">
                  <div class="source-name" title="${statusTooltip}">
                    <span>${statusDot}</span>
                    <span>${s.source_name} ${isTemp}</span>
                    ${resumableBadge}
                    ${sizeStr}
                  </div>
                  <div class="source-actions">
                    ${withheld}
                  </div>
                </div>
              `;
            }

            html += `
                </div>
              </div>
            `;
          }

          html += `
              </div>
            </div>
          `;
        }

        html += `
            </div>
          </div>
        `;
      }

      container.innerHTML = html;
    }

    let currentActiveStreamUrl = '';

    function openStreamPlayer(sourceId, sourceName, postTitle) {
      const streamUrl = `${window.location.origin}/api/v1/stream?id=${sourceId}&redirect=1`;
      currentActiveStreamUrl = streamUrl;
      document.getElementById('player-title').innerText = postTitle || 'Media Stream';
      document.getElementById('player-subtitle').innerText = `${sourceName} · Live JIT Resolver`;
      const video = document.getElementById('html5-video');
      video.src = streamUrl;
      video.load();
      video.play().catch(() => {});

      document.getElementById('player-vlc-btn').href = `vlc://${streamUrl}`;
      document.getElementById('player-mpv-btn').href = `intent:${streamUrl}#Intent;package=is.xyz.mpv;type=video/*;end`;
      document.getElementById('player-raw-btn').href = streamUrl;
      document.getElementById('player-modal').style.display = 'flex';
    }

    function closePlayerModal() {
      const modal = document.getElementById('player-modal');
      const video = document.getElementById('html5-video');
      if (video) {
        video.pause();
        video.src = '';
      }
      if (modal) modal.style.display = 'none';
    }

    function copyCurrentStreamUrl() {
      if (currentActiveStreamUrl) {
        copyToClipboard(currentActiveStreamUrl);
      }
    }

    // Initial load
    fetchData();
  </script>

  <!-- Video Player Modal -->
  <div id="player-modal" class="modal-overlay" style="display:none;" onclick="if(event.target===this)closePlayerModal()">
    <div class="modal-content">
      <div class="modal-header">
        <div>
          <h3 id="player-title" style="margin:0; font-size:16px; color:#fff;">Stream Player</h3>
          <span id="player-subtitle" style="font-size:12px; color:var(--text-dim);">Live JIT Stream</span>
        </div>
        <button class="modal-close" onclick="closePlayerModal()">✕</button>
      </div>
      <div style="background:#000; border-radius:8px; overflow:hidden; margin:12px 0;">
        <video id="html5-video" controls autoplay playsinline style="width:100%; max-height:460px; display:block; background:#000;"></video>
      </div>
      <div style="display:flex; gap:8px; flex-wrap:wrap; justify-content:space-between; align-items:center;">
        <div style="display:flex; gap:6px; flex-wrap:wrap;">
          <a id="player-vlc-btn" href="#" class="btn-action" style="background:#ea580c; color:white;">🎬 VLC Player</a>
          <a id="player-mpv-btn" href="#" class="btn-action" style="background:#7c3aed; color:white;">⚡ MPV Player</a>
          <a id="player-raw-btn" href="#" target="_blank" class="btn-action" style="background:#059669; color:white;">↗ Direct Window</a>
        </div>
        <button id="player-copy-btn" class="btn-action" onclick="copyCurrentStreamUrl()">📋 Copy Stream URL</button>
      </div>
    </div>
  </div>
</body>
</html>
"""

MOBILE_CLIENT_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <meta name="theme-color" content="#090d16">
  <title>RaddStream · Mobile Web Player & Client</title>
  <style>
    :root {
      --bg: #090d16;
      --card-bg: #111827;
      --card-border: #1f2937;
      --accent: #6366f1;
      --accent-glow: rgba(99, 102, 241, 0.3);
      --emerald: #10b981;
      --amber: #f59e0b;
      --rose: #ef4444;
      --text: #f3f4f6;
      --text-muted: #9ca3af;
      --text-dim: #6b7280;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; -webkit-tap-highlight-color: transparent; }
    body {
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      padding-bottom: 40px;
    }
    header {
      position: sticky;
      top: 0;
      z-index: 100;
      background: rgba(9, 13, 22, 0.94);
      backdrop-filter: blur(12px);
      border-bottom: 1px solid var(--card-border);
      padding: 12px 14px;
    }
    .top-bar {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 10px;
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 6px;
      font-size: 16px;
      font-weight: 800;
      color: #fff;
    }
    .brand-badge {
      background: var(--accent);
      color: #fff;
      font-size: 9px;
      font-weight: 900;
      padding: 2px 5px;
      border-radius: 4px;
      text-transform: uppercase;
    }
    .header-links {
      display: flex;
      gap: 6px;
    }
    .icon-btn {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      color: var(--text-muted);
      padding: 5px 9px;
      border-radius: 6px;
      font-size: 11px;
      font-weight: 600;
      cursor: pointer;
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      gap: 4px;
    }
    .icon-btn:hover { color: #fff; border-color: var(--accent); }
    .search-row {
      position: relative;
      margin-bottom: 8px;
    }
    .search-input {
      width: 100%;
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      color: #fff;
      font-size: 14px;
      padding: 8px 12px 8px 34px;
      border-radius: 8px;
      outline: none;
    }
    .search-input:focus { border-color: var(--accent); box-shadow: 0 0 0 2px var(--accent-glow); }
    .search-icon {
      position: absolute;
      left: 10px;
      top: 50%;
      transform: translateY(-50%);
      color: var(--text-dim);
      font-size: 13px;
      pointer-events: none;
    }
    .filter-chips {
      display: flex;
      gap: 6px;
      overflow-x: auto;
      scrollbar-width: none;
    }
    .filter-chips::-webkit-scrollbar { display: none; }
    .chip {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      color: var(--text-muted);
      padding: 4px 10px;
      border-radius: 14px;
      font-size: 11px;
      font-weight: 600;
      white-space: nowrap;
      cursor: pointer;
    }
    .chip.active {
      background: var(--accent);
      color: #fff;
      border-color: var(--accent);
    }
    .container {
      padding: 12px;
      max-width: 800px;
      margin: 0 auto;
    }
    .card-list {
      display: flex;
      flex-direction: column;
      gap: 10px;
    }
    .media-card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 12px;
      padding: 10px;
      display: flex;
      gap: 10px;
      cursor: pointer;
      transition: border-color 0.15s;
    }
    .media-card:hover { border-color: #374151; }
    .poster-box {
      width: 65px;
      height: 95px;
      border-radius: 6px;
      background: #1e293b;
      overflow: hidden;
      flex-shrink: 0;
      display: flex;
      align-items: center;
      justify-content: center;
    }
    .poster-img {
      width: 100%;
      height: 100%;
      object-fit: cover;
    }
    .card-content {
      flex: 1;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      min-width: 0;
    }
    .card-title {
      font-size: 14px;
      font-weight: 700;
      color: #fff;
      line-height: 1.3;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .meta-row {
      display: flex;
      gap: 4px;
      align-items: center;
      flex-wrap: wrap;
      margin-top: 4px;
    }
    .pill {
      font-size: 9px;
      font-weight: 700;
      padding: 2px 5px;
      border-radius: 4px;
      text-transform: uppercase;
    }
    .pill-type { background: #312e81; color: #c7d2fe; }
    .pill-year { background: #1f2937; color: var(--text-muted); }
    .pill-imdb { background: #78350f; color: #fde047; border: 1px solid #d97706; }
    .card-footer {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-top: 6px;
      font-size: 11px;
      color: var(--text-dim);
    }
    .btn-detail {
      background: var(--accent);
      color: #fff;
      border: none;
      padding: 4px 10px;
      border-radius: 5px;
      font-size: 11px;
      font-weight: 700;
      cursor: pointer;
    }

    /* Modal Sheet */
    .modal-overlay {
      position: fixed; inset: 0; background: rgba(0,0,0,0.85); z-index: 1000;
      display: flex; align-items: flex-end; justify-content: center;
    }
    .modal-sheet {
      background: #111827; border-top: 1px solid var(--card-border);
      border-radius: 16px 16px 0 0; width: 100%; max-width: 600px;
      max-height: 85vh; display: flex; flex-direction: column; overflow: hidden;
      animation: slideUp 0.2s ease-out;
    }
    @keyframes slideUp { from { transform: translateY(100%); } to { transform: translateY(0); } }
    .sheet-header {
      padding: 14px; border-bottom: 1px solid var(--card-border);
      display: flex; justify-content: space-between; align-items: center;
    }
    .sheet-body {
      padding: 14px; overflow-y: auto; flex: 1;
    }
    .sheet-title { font-size: 15px; font-weight: 800; color: #fff; }
    .close-btn {
      background: none; border: none; color: var(--text-muted);
      font-size: 20px; cursor: pointer; padding: 4px; line-height: 1;
    }
    .video-wrap {
      background: #000; border-radius: 8px; overflow: hidden; margin-bottom: 12px;
    }
    video { width: 100%; max-height: 240px; display: block; background: #000; }
    .player-actions {
      display: grid; grid-template-columns: repeat(2, 1fr); gap: 6px; margin-bottom: 12px;
    }
    .action-btn {
      padding: 8px 10px; border-radius: 6px; border: none; font-size: 11px;
      font-weight: 700; cursor: pointer; display: flex; align-items: center;
      justify-content: center; gap: 4px; text-decoration: none; text-align: center;
    }
    .btn-vlc { background: #ea580c; color: white; }
    .btn-mpv { background: #7c3aed; color: white; }
    .btn-mx { background: #0284c7; color: white; }
    .btn-copy { background: #374151; color: white; }
    .release-group {
      background: #090d16; border: 1px solid var(--card-border);
      border-radius: 8px; padding: 10px; margin-bottom: 8px;
    }
    .release-hdr {
      font-size: 12px; font-weight: 700; color: #fff; margin-bottom: 6px;
      display: flex; justify-content: space-between; align-items: center;
    }
    .stream-row {
      display: flex; justify-content: space-between; align-items: center;
      background: #111827; padding: 6px 8px; border-radius: 6px;
      margin-top: 5px; border: 1px solid #1f2937;
    }
    .stream-name { font-size: 11px; font-weight: 600; color: #e5e7eb; }
    .btn-play-stream {
      background: #2563eb; color: #fff; border: none; padding: 4px 10px;
      border-radius: 4px; font-size: 11px; font-weight: 700; cursor: pointer;
    }
    .toast {
      position: fixed; bottom: 20px; left: 50%; transform: translateX(-50%);
      background: #10b981; color: #fff; padding: 6px 14px; border-radius: 6px;
      font-size: 11px; font-weight: 700; display: none; z-index: 9999;
    }
  </style>
</head>
<body>
  <header>
    <div class="top-bar">
      <div class="brand">
        <span>⚡ RADD STREAM</span>
        <span class="brand-badge">CLIENT v1</span>
      </div>
      <div class="header-links">
        __RULES_BUTTON__
        <a href="/" class="icon-btn">🖥️ DB Explorer</a>
      </div>
    </div>
    <div class="search-row">
      <span class="search-icon">🔍</span>
      <input type="text" id="mobile-search" class="search-input" placeholder="Search movies, anime, series..." oninput="handleSearch()">
    </div>
    <div class="filter-chips">
      <button class="chip active" onclick="setChipFilter('', this)">All</button>
      <button class="chip" onclick="setChipFilter('movie', this)">🍿 Movies</button>
      <button class="chip" onclick="setChipFilter('series', this)">📺 Series</button>
      <button class="chip" onclick="setChipFilter('anime', this)">🎨 Anime</button>
    </div>
  </header>

  <div class="container">
    <div id="media-list" class="card-list">
      <div style="text-align:center; padding:40px 10px; color:var(--text-dim); font-size:13px;">
        Loading catalog...
      </div>
    </div>
  </div>

  <!-- Detail & Player Modal Sheet -->
  <div id="sheet-modal" class="modal-overlay" style="display:none;" onclick="if(event.target===this)closeSheetModal()">
    <div class="modal-sheet">
      <div class="sheet-header">
        <div class="sheet-title" id="sheet-title">Media Detail</div>
        <button class="close-btn" onclick="closeSheetModal()">✕</button>
      </div>
      <div class="sheet-body">
        <div id="player-container" style="display:none;">
          <div class="video-wrap">
            <video id="sheet-video" controls playsinline></video>
          </div>
          <div class="player-actions">
            <a id="btn-vlc-action" href="#" class="action-btn btn-vlc">🎬 VLC</a>
            <a id="btn-mpv-action" href="#" class="action-btn btn-mpv">⚡ MPV</a>
            <a id="btn-mx-action" href="#" class="action-btn btn-mx">📱 MX Player</a>
            <button class="action-btn btn-copy" onclick="copySheetStream()">📋 Copy Link</button>
          </div>
        </div>
        <div id="sheet-releases">
          <div style="text-align:center; padding:20px; color:var(--text-dim);">Loading releases...</div>
        </div>
      </div>
    </div>
  </div>

  <!-- Rules & System Modal -->
  <div id="rules-modal" class="modal-overlay" style="display:none;" onclick="if(event.target===this)closeRulesModal()">
    <div class="modal-sheet">
      <div class="sheet-header">
        <div class="sheet-title">⚙️ Client Extraction Rules</div>
        <button class="close-btn" onclick="closeRulesModal()">✕</button>
      </div>
      <div class="sheet-body" id="rules-content" style="font-size:12px; line-height:1.6;">
        Loading rules...
      </div>
    </div>
  </div>

  <div id="mobile-toast" class="toast">Link copied!</div>

  <script>
""" + ESCAPE_CORE_JS + """    let currentType = '';
    let searchTimer = null;
    let activeStreamUrl = '';
    // The same data-attribute rule the dashboard follows: nothing a scraper wrote
    // goes inside an `on*=` attribute, because that is a script context an escaper
    // cannot protect.
    const CLIENT_ACTIONS = {
      'open-detail': el => openDetail(num(el.dataset.value)),
      'play-source': el => playSource(el.dataset.value, el.dataset.name, el.dataset.title),
    };
    document.addEventListener('click', event => {
      const trigger = event.target.closest('[data-action]');
      if (!trigger) return;
      const handler = Object.prototype.hasOwnProperty.call(CLIENT_ACTIONS, trigger.dataset.action)
        ? CLIENT_ACTIONS[trigger.dataset.action] : null;
      if (handler) handler(trigger);
    });

    async function loadPosts(query = '', type = '') {
      const container = document.getElementById('media-list');
      try {
        const url = `/api/v1/posts?limit=30&q=${encodeURIComponent(query)}&type=${encodeURIComponent(type)}`;
        const res = await fetch(url);
        const data = await res.json();
        const results = data.results || [];
        if (results.length === 0) {
          container.innerHTML = '<div style="text-align:center; padding:40px; color:var(--text-dim); font-size:13px;">No media found.</div>';
          return;
        }
        let html = '';
        for (const p of results) {
          const typeBadge = p.content_type ? raw(esc`<span class="pill pill-type">${p.content_type}</span>`) : '';
          const yearBadge = p.year ? raw(esc`<span class="pill pill-year">${p.year}</span>`) : '';
          const imdbBadge = p.imdb_rating ? raw(esc`<span class="pill pill-imdb">⭐ ${p.imdb_rating}</span>`) : '';
          const posterHref = safeHttpUrl(p.poster_url);
          const poster = posterHref
            ? raw(esc`<img src="${posterHref}" class="poster-img" alt="${p.clean_title}" loading="lazy" onerror="this.src='';this.alt='🎬'">`)
            : raw('<span class="poster-placeholder">🎬</span>');

          html += esc`
            <div class="media-card" data-action="open-detail" data-value="${num(p.id)}">
              <div class="poster-box">${poster}</div>
              <div class="card-content">
                <div class="card-header">
                  <div class="card-title">${p.clean_title}</div>
                  <div class="meta-row">
                    ${typeBadge}
                    ${yearBadge}
                    ${imdbBadge}
                  </div>
                </div>
                <div class="card-footer">
                  <span>${num(p.release_count || 0)} releases · ${num(p.source_count || 0)} sources</span>
                  <button class="btn-detail">View & Play ↗</button>
                </div>
              </div>
            </div>
          `;
        }
        container.innerHTML = html;
      } catch (e) {
        container.innerHTML = '<div style="text-align:center; padding:40px; color:var(--rose); font-size:13px;">Failed to load posts.</div>';
      }
    }

    function handleSearch() {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => {
        const q = document.getElementById('mobile-search').value.trim();
        loadPosts(q, currentType);
      }, 250);
    }

    function setChipFilter(type, el) {
      currentType = type;
      document.querySelectorAll('.filter-chips .chip').forEach(c => c.classList.remove('active'));
      el.classList.add('active');
      const q = document.getElementById('mobile-search').value.trim();
      loadPosts(q, currentType);
    }

    async function openDetail(postId) {
      const modal = document.getElementById('sheet-modal');
      const titleEl = document.getElementById('sheet-title');
      const container = document.getElementById('sheet-releases');
      document.getElementById('player-container').style.display = 'none';
      const video = document.getElementById('sheet-video');
      video.pause();
      video.src = '';

      modal.style.display = 'flex';
      container.innerHTML = '<div style="text-align:center; padding:20px; color:var(--text-dim);">Loading releases & sources...</div>';

      try {
        const res = await fetch(`/api/v1/posts/${postId}`);
        const json = await res.json();
        if (!json.success || !json.data) {
          container.innerHTML = '<div style="color:var(--rose);">Could not load media details.</div>';
          return;
        }
        const p = json.data;
        titleEl.innerText = p.clean_title + (p.year ? ` (${p.year})` : '');

        let html = '';
        for (const r of (p.releases || [])) {
          html += esc`
            <div class="release-group">
              <div class="release-hdr">
                <span>${r.label || r.release_title}</span>
                <span class="pill pill-year">${(r.quality || 'HD').toUpperCase()}</span>
              </div>
              <div style="font-size:11px; color:var(--text-dim); margin-bottom:6px;">
                ${raw(r.size ? esc`📦 ${r.size} · ` : '')}${raw(r.languages ? esc`🌐 ${r.languages}` : '')}
              </div>
          `;
          for (const s of (r.sources || [])) {
            const isTemp = s.is_temporary ? '⏳' : '';
            // `s.source_name` only ever exists on the operator port's response;
            // the public projection replaces it with our own neutral label.
            const name = s.label || s.source_name || 'Streaming server';
            const handle = s.stream_id || s.id;
            html += esc`
              <div class="stream-row">
                <div class="stream-name">⚡ ${name} ${isTemp}</div>
                <button class="btn-play-stream" data-action="play-source" data-value="${handle}" data-name="${name}" data-title="${p.clean_title}">▶ Play</button>
              </div>
            `;
          }
          html += '</div>';
        }
        container.innerHTML = html || '<div style="text-align:center; padding:20px; color:var(--text-dim);">No releases found.</div>';
      } catch (err) {
        container.innerHTML = '<div style="color:var(--rose);">Error loading details.</div>';
      }
    }

    function playSource(sourceId, sourceName, postTitle) {
      const streamUrl = `${window.location.origin}/api/v1/stream?id=${sourceId}&redirect=1`;
      activeStreamUrl = streamUrl;
      const playerBox = document.getElementById('player-container');
      playerBox.style.display = 'block';

      const video = document.getElementById('sheet-video');
      video.src = streamUrl;
      video.load();
      video.play().catch(() => {});

      // Configure native android intents
      document.getElementById('btn-vlc-action').href = `intent:${streamUrl}#Intent;package=org.videolan.vlc;type=video/*;end`;
      document.getElementById('btn-mpv-action').href = `intent:${streamUrl}#Intent;package=is.xyz.mpv;type=video/*;end`;
      document.getElementById('btn-mx-action').href = `intent:${streamUrl}#Intent;package=com.mxtech.videoplayer.ad;type=video/*;end`;

      playerBox.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    function closeSheetModal() {
      const video = document.getElementById('sheet-video');
      video.pause();
      video.src = '';
      document.getElementById('sheet-modal').style.display = 'none';
    }

    async function openRulesModal() {
      const modal = document.getElementById('rules-modal');
      const content = document.getElementById('rules-content');
      modal.style.display = 'flex';
      content.innerHTML = 'Loading rules...';

      try {
        const [rRes, sRes] = await Promise.all([fetch('/api/v1/rules'), fetch('/api/v1/stats')]);
        const rules = await rRes.json();
        const stats = await sRes.json();

        let rulesHtml = esc`
          <div style="background:#090d16; padding:10px; border-radius:8px; margin-bottom:12px; border:1px solid var(--card-border);">
            <div style="font-weight:700; color:#fff; margin-bottom:4px;">📊 Catalog Statistics</div>
            <div>Posts: <b>${num(stats.posts)}</b> · Releases: <b>${num(stats.releases)}</b> · Sources: <b>${num(stats.sources)}</b></div>
            <div>Active Streams: <b>${num(stats.active_sources)}</b> · Resumable: <b>${num(stats.resumable_sources)}</b></div>
          </div>
          <div style="font-weight:700; color:#fff; margin-bottom:6px;">🛠️ Client-Side Unwrapping Rules</div>
          <p style="color:var(--text-dim); margin-bottom:10px;">
            Native Android clients can resolve bridge URLs using user device IP directly using these registered regex patterns:
          </p>
        `;

        for (const [svc, conf] of Object.entries(rules.services || {})) {
          rulesHtml += esc`
            <div style="background:#090d16; border:1px solid var(--card-border); border-radius:6px; padding:8px; margin-bottom:6px;">
              <span style="font-weight:700; color:var(--accent);">${String(svc).toUpperCase()}</span> (Tier ${num(conf.tier || 1)})
              <div style="font-family:monospace; color:#a7f3d0; word-break:break-all; font-size:11px; margin-top:2px;">
                ${conf.pattern || conf.regex || conf.type || 'direct'}
              </div>
            </div>
          `;
        }

        content.innerHTML = rulesHtml;
      } catch (e) {
        content.innerHTML = '<div style="color:var(--rose);">Error loading rules.</div>';
      }
    }

    function closeRulesModal() {
      document.getElementById('rules-modal').style.display = 'none';
    }

    function copySheetStream() {
      if (activeStreamUrl) {
        navigator.clipboard.writeText(activeStreamUrl).then(() => {
          showToast('Stream link copied!');
        });
      }
    }

    function showToast(msg) {
      const t = document.getElementById('mobile-toast');
      t.innerText = msg;
      t.style.display = 'block';
      setTimeout(() => { t.style.display = 'none'; }, 2000);
    }

    // Initial load
    loadPosts();
  </script>
</body>
</html>
"""


#: Operator-only affordance in the PWA header. A list of the bridge-unwrapping
#: rules *is* a list of hosters, so on the public port the control is not merely
#: disabled — it never appears in the served HTML at all.
RULES_BUTTON_HTML = '<button class="icon-btn" onclick="openRulesModal()">⚙️ Rules</button>'


def render_mobile_client(operator: bool) -> str:
    return MOBILE_CLIENT_HTML.replace(
        "__RULES_BUTTON__", RULES_BUTTON_HTML if operator else "")


PUBLIC_LANDING_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>__PROJECT_NAME__ — catalog</title>
  <style>
    body { margin:0; padding:40px 20px; background:#0b0e14; color:#e6edf3;
           font:15px/1.6 system-ui, sans-serif; }
    .wrap { max-width:640px; margin:0 auto; }
    h1 { font-size:22px; margin:0 0 4px; }
    .sub { color:#8b98a5; margin-bottom:24px; }
    code { background:#141a24; padding:2px 6px; border-radius:4px; font-size:13px; }
    a { color:#79c0ff; }
    ul { padding-left:18px; }
  </style>
</head>
<body>
  <div class="wrap">
    <h1>__PROJECT_NAME__</h1>
    <div class="sub">Catalog API. The Android client is the product; this is the
      interface it reads.</div>
    <ul>
      <li><a href="/client">__PROJECT_NAME__ Web client</a></li>
      <li><code>GET /api/v1/posts?q=&amp;type=&amp;page=&amp;limit=</code></li>
      <li><code>GET /api/v1/search/by-media?q=&amp;duration_s=&amp;resolution=&amp;language=</code></li>
      <li><code>GET /api/v1/posts/{id}</code></li>
      <li><code>GET /api/v1/stream?id=&amp;redirect=1</code></li>
      <li><code>GET /api/v1/stats</code></li>
    </ul>
    <p class="sub">Responses carry this service's own identifiers. Server selection
      happens here, not in the client.</p>
  </div>
</body>
</html>
"""


def render_public_landing() -> str:
    import config
    return PUBLIC_LANDING_HTML.replace("__PROJECT_NAME__", config.PROJECT_NAME)


def _work_ref(row) -> str:
    """The one identifier the optional account surface accepts, minted to match `/api/v2`.

    A favorite or a resume point is only writable when the client can name the work with
    a handle this server minted; `accounts_api` parses it back and refuses anything else.
    v2 mints it from `cat_works.work_key`, which `catalog_v2.work_key_for` derives from
    exactly these columns — so deriving it the same way here yields the same key without
    requiring the v2 projection to be built. The handle is an encrypted, tagged token:
    a source site or hoster name cannot ride along, and it reveals nothing a v1 caller
    did not already receive in the same payload.
    """
    title = row["clean_title"] or row["title"] or ""
    work_type = catalog_v2.work_type_for(
        row["content_type"] or "movie", int(row["is_animated"] or 0), title)
    key = catalog_v2.work_key_for(
        title, row["year"], work_type, row["imdb_id"] or "", row["tmdb_id"])
    return redact.mint_text(key, signing_secret())


def _subtitled_posts(conn, post_ids) -> dict:
    """Which of these works have at least one subtitled print, in the label's own words.

    Subtitles belong to a release, not to the post row, so the answer is an existence
    test — and it is the print grammar's answer, not a second vocabulary: `describe()`
    is what the detail route already runs per release.

    Two things keep it cheap enough for a list page. The SQL prefilter keeps only rows
    whose label contains `sub`, which every subtitle pattern in `release_descriptor`
    requires, so a true positive can never be dropped; and a work stops being scanned the
    moment one subtitled print is found. `False` therefore means "no print of this work
    claims subtitles", never "unexamined".
    """
    if not post_ids:
        return {}
    import release_descriptor

    marks = ",".join("?" * len(post_ids))
    rows = conn.execute(
        "SELECT post_id, release_title, quality, codec, languages FROM releases"
        f" WHERE post_id IN ({marks})"
        "   AND (lower(release_title) LIKE '%sub%'"
        "     OR lower(COALESCE(quality, '')) LIKE '%sub%'"
        "     OR lower(COALESCE(codec, '')) LIKE '%sub%')",
        list(post_ids),
    ).fetchall()
    flags = {int(pid): False for pid in post_ids}
    for row in rows:
        pid = int(row["post_id"])
        if flags[pid]:
            continue
        described = release_descriptor.describe(
            release_title=row["release_title"],
            quality=row["quality"],
            codec=row["codec"],
            languages=row["languages"],
        )
        flags[pid] = bool((described.get("subtitles") or {}).get("available"))
    # Gap A3: a print with stored subtitle tracks is subtitled even when
    # no label claims it — the tracks are the ground truth, the label is
    # the fallback. One indexed join; a missing table (a database that
    # never stored a track) is not an error.
    try:
        tracked = conn.execute(
            "SELECT DISTINCT r.post_id FROM releases r"
            " JOIN download_sources s ON s.release_id = r.id"
            " JOIN subtitle_tracks t ON t.link_id = s.id"
            f" WHERE r.post_id IN ({marks})",
            list(post_ids),
        ).fetchall()
    except sqlite3.OperationalError:
        tracked = []
    for row in tracked:
        flags[int(row["post_id"])] = True
    return flags


#: How far into the ledger one public list page may skip. `bounded_int` caps each
#: number on its own, so `?page=1000000&limit=100` is a pair of legal values whose
#: product asks SQLite to walk `OFFSET 99,999,900` and pay a full filtered
#: `COUNT(*)` for it; the product is what has to be bounded.
POSTS_MAX_OFFSET = 10_000

#: Cap on the `/api/v1/posts` trigram candidate set — the same 900 the
#: detail group scan uses (`_WORKS_GROUP_TRIGRAM_LIMIT`): under
#: SQLite's 999-variable cap with room for the query's other params.
#: A candidate set that would be truncated at the cap is not used at
#: all (the caller falls back to the LIKE scan) rather than risk
#: dropping a member.
_POSTS_TRIGRAM_LIMIT = 900
#: Params the `/api/v1/posts` statements reserve alongside the
#: candidate IN-list: 4 for the LIKE that verifies the candidates,
#: 10 for the facet filters, 100 for the step-2 page ids (the page
#: limit is clamped to 100), 10 of margin. The effective candidate
#: limit is `999 - reserve - len(hidden)`, so the hides the operator
#: set in the panel are counted before the list is sized.
_POSTS_TRIGRAM_RESERVE = 124


def _fuzzy_post_ids(conn, query):
    """Post ids whose title is one edit away from the query, token by token.

    The candidate pass is one trigram MATCH (`fts_posts_tri`, 15–52 ms)
    when the index exists — or one LIKE scan over the same 3-grams when
    it does not — capped at 200 rows. The true check is in Python
    (Damerau ≤ 1, so a transposition counts), so a shared gram never
    smuggles in a title that is two edits away. The adult clause
    applies here too; the operator's hides apply in the caller, where
    the ids only ever replace the LIKE clause.
    """
    tokens = search_fuzzy.fuzzy_tokens(query)
    if not tokens:
        return []
    grams = sorted({gram for token in tokens for gram in search_fuzzy.candidate_grams(token)})
    if not grams:
        return []
    ids = fts_posts.trigram_candidate_ids(
        conn, fts_posts.trigram_match(grams), search_fuzzy.CANDIDATE_LIMIT)
    if ids is not None:
        if not ids:
            return []
        placeholders = ", ".join("?" for _ in ids)
        rows = conn.execute(
            f"SELECT p.id, p.clean_title FROM posts p"
            f" WHERE {redact.adult_clause('p')}"
            f" AND p.id IN ({placeholders})",
            ids).fetchall()
        order = {pid: i for i, pid in enumerate(ids)}
        rows = sorted(rows, key=lambda row: order.get(int(row["id"]), len(ids)))
    else:
        like_sql = " OR ".join("lower(p.clean_title) LIKE ?" for _ in grams)
        rows = conn.execute(
            f"SELECT p.id, p.clean_title FROM posts p WHERE {redact.adult_clause('p')}"
            f" AND ({like_sql}) ORDER BY p.id DESC LIMIT {search_fuzzy.CANDIDATE_LIMIT}",
            [f"%{gram}%" for gram in grams]).fetchall()
    matched = []
    for row in rows:
        title_tokens = search_fuzzy.tokenize(row["clean_title"] or "")
        if search_fuzzy.fuzzy_match(tokens, title_tokens):
            matched.append(row["id"])
        if len(matched) >= 20:
            break
    return matched


def _posts_search_candidate_ids(conn, query, limit):
    """Post ids that can match a `/api/v1/posts` substring search, or None.

    The trigram candidate pass for the search's four-column LIKE
    (`clean_title`, `title`, `slug`, `cast_names`): the query's 3-grams
    are OR-matched against `fts_posts_tri`, which indexes
    `clean_title` + `cast_names`. A row whose title, slug or cast
    contains the query contains every gram of it, so the MATCH is a
    superset — the same guarantee the detail group scan relies on
    (`_works_title_candidate_ids`). The caller keeps the LIKE as the
    verifier: a shared gram is not a substring match (`Salaar` shares
    grams with `Salary Man`), so the candidates narrow the scan, they
    do not replace the match.

    None means "scan the whole table instead", and it is returned
    whenever the pass cannot prove it is a superset: no grams (a
    one-letter or punctuation-only query — `q=a` and `q=%` are
    answered by the LIKE, as before), a non-positive limit, a missing
    or empty trigram index, a trigram index that predates `cast_names`
    (`fts_posts.trigram_covers_cast` — the live shape until a rebuild),
    or a candidate set that would be truncated at the cap. The
    truncation rule is the same as the detail scan's: a set that
    fills the window might hold more, so it is not used at all rather
    than risk dropping a member.
    """
    tokens = search_fuzzy.tokenize(query)
    grams = sorted({gram for token in tokens
                    for gram in search_fuzzy.candidate_grams(token)})
    if not grams or limit <= 0:
        return None
    if not fts_posts.trigram_covers_cast(conn):
        return None
    ids = fts_posts.trigram_candidate_ids(
        conn, fts_posts.trigram_match(grams), limit)
    if ids is None or len(ids) >= limit:
        return None
    return ids


def _resolve_work_ref(conn, work_ref: str):
    """The post id a minted work handle names, or None.

    The handle is unminted with this server's own signing secret, so a forged
    or foreign handle is not a row — it is nothing, and the caller answers an
    empty page, never an error. The raw key is one of the three shapes
    `catalog_v2.work_key_for` mints: `imdb:tt…` and `tmdb:…` match the id
    columns; `family:normalized title:year` matches the title the same way
    the key was derived from it (the UDF is registered on this connection
    only, and only for this lookup). When the year is known, `idx_posts_year`
    seeks that year's rows before the UDF runs; a no-year key ("ny") still
    pays the full scan, because it has no term to seek on. The family is
    checked in Python, because the ledger
    stores the content type, not the family. The adult clause applies at
    every step: a flagged work is indistinguishable from a missing one.
    """
    key = redact.parse_text(work_ref, signing_secret())
    if not key:
        return None
    if key.startswith("imdb:"):
        row = conn.execute(
            f"SELECT id FROM posts p WHERE {redact.adult_clause('p')} AND p.imdb_id = ?"
            " ORDER BY id DESC LIMIT 1", (key[5:],)).fetchone()
        return int(row["id"]) if row else None
    if key.startswith("tmdb:"):
        row = conn.execute(
            f"SELECT id FROM posts p WHERE {redact.adult_clause('p')} AND p.tmdb_id = ?"
            " ORDER BY id DESC LIMIT 1", (key[5:],)).fetchone()
        return int(row["id"]) if row else None
    parts = key.split(":")
    if len(parts) != 3:
        return None
    family, title, year = parts
    if family not in ("movie", "series") or not title:
        return None
    conn.create_function(
        "radd_norm_title", 1, catalog_v2.normalize_title, deterministic=True)
    sql = ("SELECT id, clean_title, title, year, content_type, is_animated"
           " FROM posts p"
           f" WHERE {redact.adult_clause('p')}"
           " AND radd_norm_title(COALESCE(p.clean_title, p.title)) = ?")
    params = [title]
    if year != "ny":
        try:
            params.append(int(year))
        except ValueError:
            return None
        sql += " AND p.year = ?"
    sql += " ORDER BY id DESC"
    for row in conn.execute(sql, params).fetchall():
        work_type = catalog_v2.work_type_for(
            row["content_type"] or "movie", int(row["is_animated"] or 0),
            row["clean_title"] or row["title"] or "")
        if catalog_v2.work_family(work_type) == family:
            return int(row["id"])
    return None


#: The year a title actually came out, as the list should walk it. Scraped
#: years are dirty — 2099, 2077 and 2067 all sit in the live ledger, mostly
#: titles that swallowed a wrong number ("Cyberpunk 2077") — and a missing
#: year is NULL or 0, so the raw value cannot be trusted as an order key.
#: A year outside 1900..next-year counts as unknown and sorts with the
#: missing years, last. `strftime` keeps the ceiling current without a
#: code change every January.
_NEWEST_YEAR_SQL = (
    "CASE WHEN p.year BETWEEN 1900 AND CAST(strftime('%Y', 'now') AS INTEGER) + 1 "
    "THEN p.year ELSE 0 END"
)


#: A single /api/v1/posts search may not run longer than this. Live nginx
#: reads the posts location in 15 s; 10 s leaves headroom for the JSON encode
#: and the proxy hop, and turns a pathological query into a 503 instead of a
#: hung worker thread (Session 125 scale quick wins).
SEARCH_DEADLINE_SECONDS = 10.0


#: The 10 genre categories the panel seeded (gap A18) and the facets
#: endpoint reports. The `genre=` filter and the facets counts share the
#: predicates below, so a facet count is exactly the number of rows the
#: matching filter returns — a chip must never promise a count its tap
#: cannot deliver.
GENRE_KEYS = ("action", "adventure", "animation", "comedy", "crime",
              "drama", "horror", "romance", "sci-fi", "thriller")

#: genre key -> (SQL fragment on alias `p`, params). A plain token is one
#: `lower(p.genres) LIKE ?`; sci-fi keeps the four spellings the filter
#: already matched, and animation also matches the `is_animated` flag the
#: ledger actually writes (a cartoon whose genres never say "animation"
#: is still animation).
GENRE_FILTER_SQL = {
    "action": ("lower(p.genres) LIKE ?", ["%action%"]),
    "adventure": ("lower(p.genres) LIKE ?", ["%adventure%"]),
    "animation": ("(lower(p.genres) LIKE ? OR lower(p.genres) LIKE ?"
                  " OR p.is_animated = 1)", ["%animation%", "%anime%"]),
    "comedy": ("lower(p.genres) LIKE ?", ["%comedy%"]),
    "crime": ("lower(p.genres) LIKE ?", ["%crime%"]),
    "drama": ("lower(p.genres) LIKE ?", ["%drama%"]),
    "horror": ("lower(p.genres) LIKE ?", ["%horror%"]),
    "romance": ("lower(p.genres) LIKE ?", ["%romance%"]),
    "sci-fi": ("(lower(p.genres) LIKE ? OR lower(p.genres) LIKE ?"
               " OR lower(p.genres) LIKE ? OR lower(p.genres) LIKE ?)",
               ["%sci-fi%", "%sci fi%", "%scifi%", "%science fiction%"]),
    "thriller": ("lower(p.genres) LIKE ?", ["%thriller%"]),
}

#: industry key -> SQL fragment on alias `p` (no params; the values are
#: fixed). The `industry=` filter and the facets counts share these, for
#: the same reason as the genre predicates above.
INDUSTRY_FILTER_SQL = {
    "bollywood": "lower(p.industry) LIKE '%bollywood%'",
    "hollywood": "lower(p.industry) LIKE '%hollywood%'",
    "pakistani": ("(lower(p.industry) LIKE '%pakistan%'"
                  " OR lower(p.country) LIKE '%pakistan%'"
                  " OR lower(p.language) LIKE '%urdu%')"),
    "south_indian": ("(lower(p.industry) LIKE '%south%'"
                     " OR lower(p.industry) LIKE '%tollywood%'"
                     " OR lower(p.industry) LIKE '%kollywood%'"
                     " OR lower(p.industry) LIKE '%mollywood%'"
                     " OR lower(p.industry) LIKE '%sandalwood%'"
                     " OR lower(p.language) LIKE '%tamil%'"
                     " OR lower(p.language) LIKE '%telugu%'"
                     " OR lower(p.language) LIKE '%malayalam%'"
                     " OR lower(p.language) LIKE '%kannada%')"),
    "anime": "(p.is_animated = 1 OR lower(p.industry) LIKE '%anime%')",
    # Region keys (work-centric API): the ledger files these three
    # regions across industry / country / language with no single
    # column to trust — industry says `china` (1,385 rows), country
    # says `china` (1,870), language says `chinese` (695) — so the
    # predicate is the union, measured live 2026-11-12. Turkish is
    # the same shape (588 rows across the three columns).
    "chinese": ("(lower(p.industry) LIKE '%chinese%'"
                " OR lower(p.industry) LIKE '%china%'"
                " OR lower(p.country) LIKE '%china%'"
                " OR lower(p.language) LIKE '%chinese%'"
                " OR lower(p.language) LIKE '%mandarin%'"
                " OR lower(p.language) LIKE '%cantonese%')"),
    "korean": ("(lower(p.industry) LIKE '%korean%'"
               " OR lower(p.industry) LIKE '%korea%'"
               " OR lower(p.country) LIKE '%korea%'"
               " OR lower(p.language) LIKE '%korean%')"),
    "turkish": ("(lower(p.industry) LIKE '%turkish%'"
                " OR lower(p.industry) LIKE '%turkey%'"
                " OR lower(p.country) LIKE '%turk%'"
                " OR lower(p.language) LIKE '%turkish%')"),
}

INDUSTRY_KEYS = tuple(INDUSTRY_FILTER_SQL)

INDUSTRY_LABELS = {
    "bollywood": "Bollywood",
    "hollywood": "Hollywood",
    "pakistani": "Pakistani",
    "south_indian": "South Indian",
    "anime": "Anime",
    "chinese": "Chinese",
    "korean": "Korean",
    "turkish": "Turkish",
}

#: content_type -> display label for the facets types group. A type the
#: ledger has not written yet falls back to a title-cased key.
TYPE_LABELS = {
    "movie": "Movies",
    "series": "Series",
    "complete_season": "Complete seasons",
    "ongoing_season": "Ongoing seasons",
}


def _like_escape(value: str) -> str:
    """Escape a value for use inside a LIKE pattern (`%`, `_`, `\\`).

    The value is caller- or seed-supplied text, not a fixed key, so an
    unescaped `%` would match every row and an unescaped `_` any single
    character. Use with `LIKE ? ESCAPE '\\'`.
    """
    return (value.replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_"))


def _genre_tokens(genres) -> list[str]:
    """Normalize a posts.genres / posts.language / cast_names value into
    lowercase tokens.

    Accepts a JSON array (`[\"Action\", \"Drama\"]`), a comma-separated
    string (\"Action, Horror\"), or a single plain string (\"Action\").
    Blank, \"[]\", and unparseable values yield []. Same shape as
    `backfill_categories.parse_genre_tokens`, kept local so the serve
    path does not import a data-job script.
    """
    if not genres:
        return []
    text = str(genres).strip()
    if not text or text == "[]":
        return []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            parsed = None
        if isinstance(parsed, list):
            return [str(t).strip().lower() for t in parsed if str(t).strip()]
        # Malformed JSON array: fall through to comma-split.
    return [t.strip().lower() for t in text.split(",") if t.strip()]


def _enrich_post_rows(conn, rows, base_url: str) -> list[dict]:
    """Project page rows the way /api/v1/posts does: the `post_brief`
    view, the art pair, the work handle, and the subtitled flag."""
    subtitled = _subtitled_posts(conn, [r["id"] for r in rows])
    results = []
    for r in rows:
        item = redact.project(r, "post_brief")
        item.update(_art_pair(r, base_url))
        item["work_ref"] = _work_ref(r)
        item["subtitled"] = bool(subtitled.get(int(r["id"]), False))
        results.append(item)
    return results


#: A search that matches more than this many rows is too broad to dedupe
#: exactly (a one-letter query matches the catalog); it keeps the row page
#: and its row total instead of paying a full-catalog grouping. Real
#: title searches match far fewer — "salaar" is 8 rows live.
_SEARCH_DEDUPE_CAP = 1000


def _dedupe_page_rows(rows):
    """One row per work within a page, in the page's own order.

    Audit #17: a rail must not show the same film twice. The page keeps
    its order (a work sits where its earliest row sat) and its
    representative is the best-printed row; `total` is untouched, so a
    deduped page may simply be shorter than `limit` — the count counts
    rows, the page shows works. Cross-page repeats are out of scope:
    the trending order is a join, so a whole-catalog grouping would
    cost the scan this avoids.
    """
    if len(rows) < 2:
        return list(rows)
    candidates = []
    for r in rows:
        try:
            candidates.append({
                "id": int(r["id"]),
                "clean_title": r["clean_title"] or "",
                "title": r["title"] or "",
                "year": r["year"],
                "content_type": r["content_type"] or "",
                "release_count": int(r["release_count"] or 0),
                "source_count": int(r["source_count"] or 0),
            })
        except (KeyError, IndexError, TypeError, ValueError):
            continue
    if not candidates:
        return list(rows)
    position = {int(c["id"]): i for i, c in enumerate(candidates)}
    groups = title_clean.group_work_rows(candidates)
    groups.sort(key=lambda g: min(position[int(c["id"])] for c in g))
    keep = {int(title_clean.representative(g)["id"]) for g in groups}
    return [r for r in rows if int(r["id"]) in keep]


def _dedupe_search_page(conn, where_sql, params, step1_order, page, limit):
    """(page_ids, deduped_total): one representative id per work.

    Audit #38: the same film filed by eight sites is one search row, not
    eight. The candidates are fetched id-only (bounded by the cap), grouped
    by work in Python, and paginated over groups — so the page keeps the
    search's own order (a group's position is its earliest member's) and
    `total` counts works, not rows. The representative is the row with the
    most prints, then mirrors, then the newest id.
    """
    rows = conn.execute(
        "SELECT p.id, p.clean_title, p.title, p.year, p.content_type"
        " FROM posts p "
        f"WHERE {where_sql} ORDER BY {step1_order}",
        params).fetchall()
    if not rows:
        return [], 0
    ids = [int(r["id"]) for r in rows]
    counts: dict[int, tuple[int, int]] = {}
    marks = ",".join("?" * len(ids))
    for row in conn.execute(
            "SELECT r.post_id, COUNT(DISTINCT r.id), COUNT(DISTINCT s.id)"
            " FROM releases r"
            " LEFT JOIN download_sources s ON s.release_id = r.id"
            f" WHERE r.post_id IN ({marks}) GROUP BY r.post_id",
            ids).fetchall():
        counts[int(row[0])] = (int(row[1]), int(row[2]))
    position = {post_id: index for index, post_id in enumerate(ids)}
    candidates = [{
        "id": int(r["id"]), "clean_title": r["clean_title"],
        "title": r["title"], "year": r["year"],
        "content_type": r["content_type"],
        "release_count": counts.get(int(r["id"]), (0, 0))[0],
        "source_count": counts.get(int(r["id"]), (0, 0))[1],
    } for r in rows]
    groups = title_clean.group_work_rows(candidates)
    # The search's own order, not popularity order: a work sits where its
    # earliest row sat in the id scan.
    groups.sort(key=lambda g: min(position[int(c["id"])] for c in g))
    total = len(groups)
    start = max(0, (page - 1) * limit)
    page_groups = groups[start:start + limit]
    return [int(title_clean.representative(g)["id"]) for g in page_groups], total


def _facet_filter_clauses(*, content_type: str = "", industry: str = "",
                          genre: str = "", language: str = "",
                          quality: str = "", free_only: bool = False):
    """The browse facet filters as WHERE clauses on alias `p`, shared by
    `/api/v1/posts` and `/api/v1/works` so a chip means the same rows on
    both surfaces. Returns (clauses, params), in the posts route's
    historical order: type, industry, genre, language, quality,
    free-only. Every value is matched against a column the ledger
    already writes, and only the fixed clauses below are interpolated
    — the request string never reaches the SQL. An unknown value is
    ignored (the honest answer is the unfiltered list), not guessed at.

    `industry` is already resolved by the caller (`industry=` wins,
    `region=` is its alias). The language value is a bucket when it
    names one (`works.language_sql`: `hindi`, `dual`, `unknown`, …)
    and falls back to the old substring LIKE otherwise, so facet chips
    (`original audio`) and old clients keep working."""
    clauses: list = []
    params: list = []
    if content_type:
        # `type=anime` is the one filter value that is not a `content_type`: the
        # ledger stores animation as a flag on the post (`is_animated`, plus an
        # `industry` of Anime) and only ever writes movie / series /
        # complete_season / ongoing_season to `content_type`. Exact equality on
        # the type column therefore answered that chip with zero rows forever.
        # Answer it from the flag the data actually carries, the way the
        # operator dashboard already counts animated titles.
        if content_type.strip().lower() == "anime":
            clauses.append("(p.is_animated = 1 OR lower(p.industry) LIKE '%anime%')")
        else:
            clauses.append("p.content_type = ?")
            params.append(content_type)

    industry_key = industry.strip().lower()
    industry_sql = INDUSTRY_FILTER_SQL.get(industry_key)
    if industry_sql:
        clauses.append(industry_sql)

    genre_key = genre.strip().lower()
    genre_sql = GENRE_FILTER_SQL.get(genre_key)
    if genre_sql:
        clauses.append(genre_sql[0])
        params.extend(genre_sql[1])

    # Language is a property of the post row, like genre. A bucket value
    # (`hindi`, `dual`, `unknown`, …) uses the normalised predicate, so a
    # Hindi+English row answers both `language=hindi` and
    # `language=dual`; anything else keeps the old substring match.
    language_key = language.strip().lower()
    if language_key:
        bucket_sql = works.language_sql(language_key)
        if bucket_sql is not None:
            clauses.append(bucket_sql[0])
            params.extend(bucket_sql[1])
        else:
            clauses.append(r"lower(p.language) LIKE ? ESCAPE '\'")
            params.append("%" + _like_escape(language_key) + "%")

    # Quality is a property of a release, not of the post row, so it is an
    # existence test over the prints: "this work has at least one 4K/1080p/720p
    # release", not "its single best release is exactly this tier".
    quality_key = quality.strip().lower()
    quality_sql = {
        "4k": "(upper(rq.quality) LIKE '%2160%' OR upper(rq.quality) LIKE '%4K%'"
              " OR upper(rq.quality) LIKE '%UHD%')",
        "1080p": "upper(rq.quality) LIKE '%1080%'",
        "720p": "upper(rq.quality) LIKE '%720%'",
    }.get(quality_key)
    if quality_sql:
        clauses.append(
            "EXISTS (SELECT 1 FROM releases rq"
            f" WHERE rq.post_id = p.id AND rq.quality IS NOT NULL AND {quality_sql})")

    if free_only:
        # "Included in my plan" for a free viewer: the work has at least
        # one print the free gate lets through. Mirrors the client's
        # VipQualityGate — 1080p/2160p/4K/UHD/Full-HD are premium, and
        # under a 480p operator cap 720p joins them. A print with no
        # quality label counts as free, the same as the client treats an
        # unknown band.
        premium_markers = ["%1080%", "%2160%", "%4K%", "%UHD%",
                           "%FULL HD%", "%FULLHD%", "%FHD%"]
        if panel_feed.read_free_quality_cap() == "480p":
            premium_markers.append("%720%")
        premium_sql = " OR ".join(
            "upper(rq.quality) LIKE ?" for _ in premium_markers)
        clauses.append(
            "EXISTS (SELECT 1 FROM releases rq WHERE rq.post_id = p.id AND"
            f" (rq.quality IS NULL OR TRIM(rq.quality) = '' OR NOT ({premium_sql})))")
        params.extend(premium_markers)
    return clauses, params


def _newest_suggestions(conn, base_url: str = "", limit: int = 5) -> list[dict]:
    """The empty-search fallback: the newest public posts, so a query
    that matches nothing still offers something to try instead of a
    bare zero. Two-step like the list route: the ids first, from
    `posts` alone (cheap), then the counts for just those ids — the
    one-query grouped shape over the whole catalog is the ~4.8 s shape
    the two-step exists to avoid. The adult clause and the panel hides
    apply exactly as on the list."""
    hidden = panel_feed.hidden_work_ids()
    hidden_sql = ""
    hidden_params: list = []
    if hidden:
        ids = sorted(hidden)[:panel_feed.HIDDEN_IDS_CAP]
        hidden_sql = " AND p.id NOT IN (%s)" % ",".join("?" for _ in ids)
        hidden_params = ids
    id_rows = conn.execute(
        "SELECT p.id FROM posts p"
        f" WHERE {redact.adult_clause('p')}{hidden_sql}"
        f" ORDER BY {_NEWEST_YEAR_SQL} DESC, p.id DESC LIMIT ?",
        hidden_params + [limit]).fetchall()
    ids = [int(r["id"]) for r in id_rows]
    if not ids:
        return []
    rows = conn.execute(
        "SELECT p.id, p.clean_title, p.title, p.year, p.content_type, p.seasons,"
        " p.poster_url, p.backdrop_urls, p.imdb_rating, p.imdb_id, p.tmdb_id,"
        " p.genres, p.is_animated, p.industry, p.country, p.language,"
        " COUNT(DISTINCT r.id) as release_count,"
        " COUNT(DISTINCT s.id) as source_count"
        " FROM posts p"
        " LEFT JOIN releases r ON r.post_id = p.id"
        " LEFT JOIN download_sources s ON s.release_id = r.id"
        " WHERE p.id IN (" + ", ".join("?" for _ in ids) + ") GROUP BY p.id",
        ids).fetchall()
    by_id = {int(r["id"]): r for r in rows}
    ordered = [by_id[i] for i in ids if i in by_id]
    return _enrich_post_rows(conn, ordered, base_url)


def _poor_match_correction(conn, query: str, result_titles) -> str | None:
    """The correction for a typo that still returned rows — or None.

    The served titles' own words are excluded from the correction:
    `salar` is one edit from the served `salary` too, and offering
    that back would be no correction at all. The next closest word
    (`salaar`) is the one worth surfacing. A correction whose every
    token is already an exact result token adds nothing and is not
    offered either — the caller only calls this after
    `works.is_poor_match` said the results match no query token."""
    exclude = set()
    for title in result_titles:
        exclude.update(search_fuzzy.tokenize(title or ""))
    correction = did_you_mean.suggest_correction(
        conn, query, exclude=frozenset(exclude))
    return correction["query"] if correction is not None else None


#: The trending order cache — why it exists. `/api/v1/trending` delegates
#: to `api_v1_get_posts(sort="trending")`, whose page is the one-query
#: shape: GROUP BY over every public post with two joins, three temp
#: B-trees (two `COUNT(DISTINCT)`, one ORDER BY) — measured 2.9 s per hit
#: from localhost at load 0.01 (2026-11-12), ~10 s cold, and nothing
#: cached it, so every hit paid it. The 0.039 s second hit the gate
#: probe saw was nginx's 60 s `radd_micro` proxy cache on the public
#: location, not this process: direct-to-service hits never saw it, and
#: public hits paid the full cost again whenever the 60 s window lapsed
#: (9.14 s / 4.90 s at 14:09–14:10). The service is one process
#: (ThreadingHTTPServer), so an in-process cache holds across requests —
#: the cache was missing, not per-process.
#:
#: What is cached is the ORDER ONLY — post ids by
#: (release_count + source_count) DESC, p.id DESC, plus the COUNT(*)
#: total at build time — never the page rows. What a client may see is
#: re-decided per request: a row flagged adult, or hidden in the panel,
#: after the order was built is re-checked here and backfilled from
#: deeper in the order, so a flag flip hides the work on the very next
#: hit and the page stays full. The fail-safe direction keeps its lag:
#: an un-flag (or un-hide) waits for the TTL, and `total` can lag the
#: same window — it is a number, never a listing. The catalog changes
#: only on batched merges, so a 120 s stale window on a browse list is
#: the same trade the works list already makes (`_WORKS_CACHE_*`).
_TRENDING_CACHE_TTL_SECONDS = 120.0
_TRENDING_CACHE_MAX_ENTRIES = 16
#: Page 1 of a rail is the hot path, but the route allows any page whose
#: offset is <= POSTS_MAX_OFFSET (10_000): cache enough ids to answer
#: every legal page from the cache, so no trending page ever pays the
#: grouping. The grouping itself costs the same whatever the LIMIT is.
_TRENDING_ORDER_TOP_N = POSTS_MAX_OFFSET + 100
#: How many extra ids a page fetch looks past when a cached id was
#: flagged or hidden after the order was built.
_TRENDING_PAGE_SLACK = 32
_TRENDING_ORDER_CACHE: dict = {}


def _trending_db_fingerprint():
    """(path, mtime_ns, size) for the catalog file, or (path,) when the
    file cannot be stat'ed. A merge or checkpoint bumps the mtime, so
    the next hit rebuilds instead of serving the pre-merge order; a
    write that lands only in the WAL leaves the fingerprint alone and
    the TTL governs — the per-request adult/hide re-check below is
    what keeps listings exact either way."""
    path = DB_PATH
    try:
        st = os.stat(path)
    except OSError:
        return (str(path),)
    return (str(path), st.st_mtime_ns, st.st_size)


def _trending_cache_get(key):
    entry = _TRENDING_ORDER_CACHE.get(key)
    if entry is None:
        return None
    expires, value = entry
    if time.monotonic() > expires:
        del _TRENDING_ORDER_CACHE[key]
        return None
    return value


def _trending_cache_put(key, value):
    if len(_TRENDING_ORDER_CACHE) >= _TRENDING_CACHE_MAX_ENTRIES:
        oldest = min(_TRENDING_ORDER_CACHE,
                     key=lambda k: _TRENDING_ORDER_CACHE[k][0])
        del _TRENDING_ORDER_CACHE[oldest]
    _TRENDING_ORDER_CACHE[key] = (time.monotonic() + _TRENDING_CACHE_TTL_SECONDS, value)


def _trending_cached_page(conn, where_sql, params, content_type,
                          limit, offset, hidden):
    """(page_ids, total) for a plain trending page from the cached
    order, or (None, None) when the caller should run the uncached
    path (the requested window runs past the cached prefix — a page
    past the legal offset cap, or a page the prefix ran out on while
    still short). An empty list (not None) means the page is genuinely
    empty: the cached order is complete and ends before this page.

    On a cache miss the build is the same one-query shape the paged
    read uses, id-only with the same ORDER BY, plus the COUNT(*) the
    caller would otherwise run — paid once per TTL, not per hit. The
    same `where_sql` (adult clause, type facet, hides at build time)
    builds it, so a cached page and an uncached page answer the same
    rows in the same order. `full` never reaches here: the caller
    only offers the fast path to the public shape."""
    key = (content_type, _trending_db_fingerprint())
    cached = _trending_cache_get(key)
    if cached is None:
        rows = conn.execute(
            "SELECT p.id FROM posts p"
            " LEFT JOIN releases r ON r.post_id = p.id"
            " LEFT JOIN download_sources s ON s.release_id = r.id"
            f" WHERE {where_sql}"
            " GROUP BY p.id"
            " ORDER BY (COUNT(DISTINCT r.id) + COUNT(DISTINCT s.id)) DESC,"
            " p.id DESC"
            f" LIMIT {_TRENDING_ORDER_TOP_N}",
            params).fetchall()
        ids = [int(r["id"]) for r in rows]
        total = conn.execute(
            f"SELECT COUNT(*) FROM posts p WHERE {where_sql}",
            params).fetchone()[0]
        _trending_cache_put(key, (ids, total))
        cached = (ids, total)
    ids, total = cached
    truncated = len(ids) >= _TRENDING_ORDER_TOP_N
    hidden_ids = set(hidden or ())
    page_ids: list[int] = []
    cursor = offset
    while len(page_ids) < limit and cursor < len(ids):
        window = ids[cursor:cursor + (limit - len(page_ids))
                     + _TRENDING_PAGE_SLACK]
        cursor += len(window)
        marks = ",".join("?" for _ in window)
        live = {int(r["id"]) for r in conn.execute(
            f"SELECT p.id FROM posts p WHERE p.id IN ({marks})"
            f" AND {redact.adult_clause('p')}",
            window).fetchall()}
        for pid in window:
            if len(page_ids) >= limit:
                break
            if pid in live and pid not in hidden_ids:
                page_ids.append(pid)
    if len(page_ids) < limit and cursor >= len(ids) and truncated:
        # The cached prefix ran out while the page was still short: the
        # order may continue past the prefix, so the caller answers
        # this page from the uncached path instead of serving a short
        # one. When the order is complete (not truncated) a short page
        # is the true answer.
        return None, None
    return page_ids, total


def api_v1_get_posts(query: str = "", content_type: str = "", page: int = 1,
                     limit: int = 20, full: bool = False,
                     base_url: str = "", industry: str = "", genre: str = "",
                     quality: str = "", sort: str = "", free_only: bool = False,
                     work_ref: str = "", language: str = "", region: str = "") -> dict:
    _ensure_schema()
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 20
    # The HTTP layer clamps limit to 1–100, but this function is also called
    # directly (tests, other modules): clamp here too, so no caller can ask
    # for an unbounded page (Session 125).
    limit = max(1, min(100, limit))
    offset = max(0, (page - 1) * limit)
    with get_db() as conn:
        # Deadline: a slow query must not hold a worker thread past the
        # nginx read timeout. The handler fires every 1000 VM instructions
        # and aborts the query by returning 1 — it must NOT raise: this
        # Python's sqlite3 module swallows a raise inside the callback and
        # the query surfaces as OperationalError("interrupted") instead.
        # The /api/v1/posts branch maps exactly that error to 503.
        deadline = time.monotonic() + SEARCH_DEADLINE_SECONDS

        def _search_deadline():
            return 1 if time.monotonic() > deadline else 0

        conn.set_progress_handler(_search_deadline, 1000)
        # Adult-flagged posts are stored in the DB but never exposed via the API
        where_clauses = [redact.adult_clause("p")]
        params = []
        # How many params the search clause (index 1) owns. The fallbacks
        # below slice `params` at this count, so it is the count of the
        # clause actually appended — 4 for the LIKE, 1 for a work_ref id,
        # 12 for a whole-word clause — never a hardcoded 4.
        search_param_count = 4
        # The operator hides are read here, not below where the clause is
        # appended, so the search branch can size the trigram candidate
        # list against them: the candidate IN-list, the LIKE, the facets
        # and the hides share SQLite's 999-variable budget.
        hidden = panel_feed.hidden_work_ids()
        if work_ref:
            # A minted handle names one work: the title search is not consulted
            # at all, and a handle that resolves to nothing answers an empty
            # page (total 0), never an error. Every other filter, the adult
            # clause and the hides below still apply on top of the one id.
            post_id = _resolve_work_ref(conn, work_ref)
            if post_id is None:
                return {
                    "page": page,
                    "limit": limit,
                    "total": 0,
                    "total_pages": 1,
                    "results": [],
                    "fuzzy": False,
                    "suggestion": None,
                }
            where_clauses.append("p.id = ?")
            params.append(post_id)
            search_param_count = 1
        elif query:
            if works.is_whole_word_query(query):
                # A single stopword ("the") or a 1–2 letter token matches
                # whole words only: `the` as a substring matches `other`,
                # `together`, `them` — 43,577 rows of junk live. Cast
                # names are excluded here: a stopword inside a cast list
                # is junk, not a match.
                clause, clause_params = works.whole_word_title_clause(query)
                where_clauses.append(clause)
                params.extend(clause_params)
                search_param_count = len(clause_params)
            else:
                # The omnibox matches actors too: `cast_names` is the scraped
                # cast list on the post, so "Shah Rukh Khan" finds his films the
                # same way a title does. The fuzzy fallback below stays
                # title-only — a mistyped actor name falls back to close titles,
                # not to guessed names.
                #
                # The LIKE below is the scan (see test_posts_query_plan.py):
                # four leading-wildcard LIKEs over the whole table, paid
                # twice per request (the COUNT, then the page's ids). When
                # the trigram index covers cast, a trigram MATCH over the
                # query's 3-grams is a superset of that LIKE, so the search
                # seeks the candidates by rowid and LIKE-verifies only
                # those, instead of scanning — the COUNT and the page both
                # read the narrowed clause, because it is clause 1. The
                # LIKE stays as the verifier: a shared gram is not a
                # substring match (`Salaar` shares grams with `Salary
                # Man`). When the index is absent, stale, or the candidate
                # set would be truncated, the clause is exactly the old
                # LIKE — same rows, same order, just slower.
                candidate_limit = max(
                    0, min(_POSTS_TRIGRAM_LIMIT,
                           999 - _POSTS_TRIGRAM_RESERVE - len(hidden)))
                candidate_ids = _posts_search_candidate_ids(
                    conn, query, candidate_limit)
                q_param = f"%{query}%"
                if candidate_ids is not None:
                    placeholders = ", ".join("?" for _ in candidate_ids)
                    where_clauses.append(
                        f"(p.id IN ({placeholders}) AND (p.clean_title LIKE ?"
                        " OR p.title LIKE ? OR p.slug LIKE ?"
                        " OR p.cast_names LIKE ?))")
                    params.extend(candidate_ids)
                    params.extend([q_param, q_param, q_param, q_param])
                    search_param_count = len(candidate_ids) + 4
                else:
                    where_clauses.append("(p.clean_title LIKE ? OR p.title LIKE ? OR p.slug LIKE ? OR p.cast_names LIKE ?)")
                    params.extend([q_param, q_param, q_param, q_param])
        # Facet filters, shared with /api/v1/works (see
        # `_facet_filter_clauses`). `region=` is the alias for
        # `industry=`; an explicit `industry=` wins.
        facet_clauses, facet_params = _facet_filter_clauses(
            content_type=content_type,
            industry=industry.strip() or region.strip(),
            genre=genre, language=language, quality=quality,
            free_only=free_only)
        where_clauses.extend(facet_clauses)
        params.extend(facet_params)

        # No play-count column exists, so "trending" cannot be invented from views.
        # Rank instead by the only popularity-adjacent figure the ledger carries:
        # how many prints and mirrors the catalog has for the work.
        # `most_copies` is the honest alias for the same order; `trending`
        # stays as the back-compatible name.
        sort_key = sort.strip().lower()
        if sort_key == "rating":
            order_sql = ("(p.imdb_rating IS NULL OR TRIM(p.imdb_rating) = '') ASC,"
                         " CAST(p.imdb_rating AS REAL) DESC, p.id DESC")
        elif sort_key == "title":
            order_sql = ("lower(COALESCE(NULLIF(TRIM(p.clean_title), ''), p.title)) ASC,"
                         " p.id DESC")
        elif sort_key in ("trending", "most_copies"):
            order_sql = "(release_count + source_count) DESC, p.id DESC"
        elif sort_key in ("", "newest"):
            # Newest-first is the default: the list walks down through time.
            # `None` marks the two-step path below — a one-query ORDER BY
            # year over the joined, grouped page must group all ~135k public
            # posts before sorting (~4.8s live), so the order is resolved
            # from `posts` alone first and imposed in Python.
            order_sql = None
        else:
            order_sql = "p.id DESC"

        where_sql = " AND ".join(where_clauses)
        # A work the operator hid in the panel stays hidden on every list,
        # including to an old app that never learned about the panel feed: the
        # hide is enforced here, at serve time, not only in the section
        # resolver. Unwired (no panel database) means no hides, never an error.
        # (`hidden` was read above, before the search branch, so the trigram
        # candidate limit could count it.)
        if hidden:
            ids = sorted(hidden)[:panel_feed.HIDDEN_IDS_CAP]
            where_clauses.append(
                "p.id NOT IN (%s)" % ",".join("?" for _ in ids))
            params.extend(ids)
            where_sql = " AND ".join(where_clauses)
        # Trending fast path (see `_TRENDING_ORDER_CACHE`): the plain
        # trending shape — no query, no work handle, no facet filter
        # beyond the type, public mode — answers its page from the
        # cached order instead of paying the full-catalog grouping on
        # every hit. Anything else (a search, a facet, `full`) falls
        # through to the uncached path below, unchanged.
        _trending_ids = None
        _trending_total = None
        if (not full and sort_key in ("trending", "most_copies")
                and not query and not work_ref
                and not industry.strip() and not region.strip()
                and not genre and not language and not quality
                and not free_only):
            _trending_ids, _trending_total = _trending_cached_page(
                conn, where_sql, params, content_type, limit,
                offset, hidden)
        if _trending_total is None:
            total = conn.execute(f"SELECT COUNT(*) FROM posts p WHERE {where_sql}", params).fetchone()[0]
        else:
            total = _trending_total

        fuzzy = False
        did_you_mean_query = None
        # Mood intent is computed for every query, not only on a miss —
        # the response reports it even when the literal search hit (a title
        # that happens to contain a mood word), the same as v2 search.
        mood_words = mood_search.moods_for_query(query) if query else []
        mood_genres = mood_search.genres_for_query(query) if query else []
        # The title LIKE is always clause 1; how many leading params it
        # owns. Every fallback below replaces clause 1 and must slice the
        # params at this count, not at a hardcoded 4 — a replacement
        # clause owns a different number of params than the LIKE it
        # replaced. The count is the search clause's own (see
        # `search_param_count` above): 4 for the LIKE, 1 for a work_ref
        # id, 12 for a whole-word clause, or N+4 for the LIKE with a
        # trigram candidate IN-list of N ids in front of it.
        title_param_count = search_param_count
        # The exact search missed: the fallbacks below run from this, and
        # the correction is offered whenever it did — even when the fuzzy
        # fallback already found rows, so the UI can say what produced them.
        exact_missed = bool(query and not work_ref and total == 0)
        if exact_missed:
            # Gap A4 — a pure mood/descriptive query ("something funny",
            # "sad love story", "mazahiya") is a feeling, not a title:
            # answer it from the genre facet instead of the title LIKE.
            # Only when no literal remainder is left — a title that
            # happens to contain a mood word was already searched
            # literally above, so the mood can never filter it out.
            if mood_genres and not mood_search.strip_mood_words(query):
                genre_clauses = []
                genre_params: list = []
                for mood_genre in mood_genres:
                    if mood_genre == "science fiction":
                        genre_clauses.append(
                            "(lower(p.genres) LIKE ? OR lower(p.genres) LIKE ?"
                            " OR lower(p.genres) LIKE ? OR lower(p.genres) LIKE ?)")
                        genre_params.extend(["%sci-fi%", "%sci fi%", "%scifi%",
                                             "%science fiction%"])
                    else:
                        genre_clauses.append("lower(p.genres) LIKE ?")
                        genre_params.append(f"%{mood_genre}%")
                where_clauses[1] = "(" + " OR ".join(genre_clauses) + ")"
                params = genre_params + params[title_param_count:]
                title_param_count = len(genre_params)
                where_sql = " AND ".join(where_clauses)
                total = conn.execute(
                    f"SELECT COUNT(*) FROM posts p WHERE {where_sql}",
                    params).fetchone()[0]
        if query and not work_ref and total == 0:
            # Exact search found nothing: one edit away is the only honest
            # second chance. The candidate ids only ever replace the LIKE
            # clause (always index 1) — every other filter, the adult
            # clause and the hides stay exactly as they were.
            fuzzy_ids = _fuzzy_post_ids(conn, query)
            if fuzzy_ids:
                where_clauses[1] = (
                    "p.id IN (%s)" % ", ".join("?" for _ in fuzzy_ids))
                params = fuzzy_ids + params[title_param_count:]
                title_param_count = len(fuzzy_ids)
                where_sql = " AND ".join(where_clauses)
                total = conn.execute(
                    f"SELECT COUNT(*) FROM posts p WHERE {where_sql}",
                    params).fetchone()[0]
                fuzzy = True
        if query and not work_ref:
            # Gap A4 — "Did you mean": the fuzzy machinery already knew the
            # correction; it just never surfaced it. Offer the corrected
            # query so the UI can show it (and the viewer can tap it) — not
            # only when the exact search missed, but also when it hit on
            # stale lookalikes ("avtar" finds old "Avtar" rows while the
            # catalog holds "Avatar"). An interrupted correction scan is
            # silence, never a failed search.
            try:
                correction = did_you_mean.suggest_correction(conn, query)
            except sqlite3.OperationalError:
                correction = None
            if correction is not None:
                did_you_mean_query = correction["query"]

        # Nothing matched at all — no exact, no fuzzy, no correction, no
        # mood: offer the newest additions instead of a bare zero. Only
        # on the miss path, and only for a real query: an unfiltered
        # empty list is normal browsing, not a failed search.
        suggestions = None
        if query and not work_ref and total == 0 and not fuzzy \
                and did_you_mean_query is None:
            suggestions = _newest_suggestions(conn, base_url)

        # Two-step page resolution: the page's ids first, from `posts` alone,
        # then the counts for just those ids. The one-query shape groups the
        # release/source fan-out for EVERY matching post before sorting, so a
        # filtered title sort (type=movie&quality=720p: 91,592 matches live)
        # ran ~2.2s warm and crossed the 10s deadline into a 503 during the
        # 2026-11-10 Firebase Robo test. The two-step applies exactly when
        # the ORDER BY names only `posts` columns: newest (year clamp),
        # title and rating. Trending orders by the join counts, so it cannot
        # resolve ids without the join: the plain trending page instead
        # takes its ids from the cached order above (`_trending_ids`,
        # None unless the fast path filled it), and a page the cache
        # cannot answer falls back to the one-query shape below. The
        # unknown sort orders by id DESC, which the rowid scan already
        # provides, so it keeps it too. No posts title index: one was
        # measured and REJECTED — the planner uses it for the content_type
        # seek, which forces the grouped shape into a GROUP BY temp B-tree
        # (title/rating/trending 7-10s, rating 503s); the two-step plus the
        # covering releases(post_id, quality) index is the fix instead.
        page_ids = _trending_ids
        two_step = order_sql is None or sort_key in ("title", "rating")
        if query and not work_ref and two_step and 0 < total <= _SEARCH_DEDUPE_CAP:
            # Audit #38: one row per film. The dedupe runs on the same
            # where-clause the count above used (adult clause, hides, all
            # filters), so the page and the total agree; the step-1 scan
            # below is skipped and step 2 fetches exactly these ids.
            step1_order = (f"{_NEWEST_YEAR_SQL} DESC, p.id DESC"
                           if order_sql is None else order_sql)
            page_ids, total = _dedupe_search_page(
                conn, where_sql, params, step1_order, page, limit)
            if not page_ids:
                return {
                    "page": page,
                    "limit": limit,
                    "total": total,
                    "total_pages": max(1, (total + limit - 1) // limit),
                    "results": [],
                    "fuzzy": fuzzy,
                    "moods": mood_words,
                    "mood_genres": mood_genres,
                    "did_you_mean": did_you_mean_query,
                    "suggestion": did_you_mean_query,
                }
        if two_step and page_ids is None:
            step1_order = (f"{_NEWEST_YEAR_SQL} DESC, p.id DESC"
                           if order_sql is None else order_sql)
            # Step 1 — the page's ids, from `posts` alone. Every clause in
            # `where_sql` names only `p.*` or a self-contained EXISTS, so no
            # join is needed here; measured ~0.34s on the live catalog
            # (page 1, title+720p) against ~2.2s for the one-query shape,
            # and no new index is needed.
            page_rows = conn.execute(
                f"SELECT p.id FROM posts p WHERE {where_sql} "
                f"ORDER BY {step1_order} LIMIT ? OFFSET ?",
                params + [limit + 1, offset]).fetchall()
            page_ids = [int(r["id"]) for r in page_rows[:limit]]
            if not page_ids:
                answer = {
                    "page": page,
                    "limit": limit,
                    "total": total,
                    "total_pages": max(1, (total + limit - 1) // limit),
                    "results": [],
                    "fuzzy": fuzzy,
                    "moods": mood_words,
                    "mood_genres": mood_genres,
                    "did_you_mean": did_you_mean_query,
                    "suggestion": did_you_mean_query,
                }
                if suggestions is not None:
                    answer["suggestions"] = suggestions
                return answer

        if page_ids is not None and not page_ids:
            # The cached trending order ends before this page: the page
            # is empty, and total is the cached count. (The two-step
            # path returns its own empty page above; this is the same
            # answer for a cached page that collected no ids — and it
            # must return here, because the step-2 query below builds
            # `p.id IN (...)` from the list, which is empty.)
            answer = {
                "page": page,
                "limit": limit,
                "total": total,
                "total_pages": max(1, (total + limit - 1) // limit),
                "results": [],
                "fuzzy": fuzzy,
                "moods": mood_words,
                "mood_genres": mood_genres,
                "did_you_mean": did_you_mean_query,
                "suggestion": did_you_mean_query,
            }
            if suggestions is not None:
                answer["suggestions"] = suggestions
            return answer

        # `p.source_site`, `p.url` and `p.slug` used to be selected here: the site
        # it came from and the page we took it off. Both are our bookkeeping, so
        # only the loopback port asks for them (`full`).
        provenance_cols = ", p.source_site, p.url, p.slug" if full else ""
        select_sql = (
            "SELECT p.id, p.clean_title, p.title, p.year, p.content_type, p.seasons,"
            " p.poster_url, p.backdrop_urls, p.imdb_rating, p.imdb_id, p.tmdb_id,"
            " p.genres, p.is_animated,"
            f" p.industry, p.country, p.language{provenance_cols},"
            " COUNT(DISTINCT r.id) as release_count,"
            " COUNT(DISTINCT s.id) as source_count"
            " FROM posts p"
            " LEFT JOIN releases r ON r.post_id = p.id"
            " LEFT JOIN download_sources s ON s.release_id = r.id"
        )
        if page_ids is not None:
            # Step 2 — counts for just this page, by id. No ORDER BY and no
            # LIMIT here: the page is already exactly these ids, and the
            # order is imposed in Python below.
            sql = (select_sql + f" WHERE {where_sql} AND p.id IN ("
                   + ", ".join("?" for _ in page_ids) + ") GROUP BY p.id")
            rows = conn.execute(sql, params + page_ids).fetchall()
        else:
            sql = (select_sql + f" WHERE {where_sql} GROUP BY p.id"
                   f" ORDER BY {order_sql} LIMIT ? OFFSET ?")
            rows = conn.execute(sql, params + [limit, offset]).fetchall()
        if sort_key in ("trending", "most_copies"):
            # Audit #17: the trending rail is the one-query path, so the
            # search dedupe above never runs on it — collapse the page
            # to one row per work here instead. `total` still counts
            # rows (see _dedupe_page_rows). `most_copies` is the same
            # order under its honest name, so it dedupes identically —
            # the two sorts must answer the same page.
            rows = _dedupe_page_rows(rows)
        if full:
            results = [dict(r) for r in rows]
        else:
            results = _enrich_post_rows(conn, rows, base_url)
        if page_ids is not None:
            # The page query fetched by id, so impose the step-1 order here.
            by_id = {}
            for item in results:
                by_id[int(item["id"])] = item
            results = [by_id[i] for i in page_ids if i in by_id]
        # The typo case with hits: the exact search returned rows, but
        # none of them contains any query token exactly (`salar` → salary
        # anime) while a correction exists — surface it instead of
        # silently serving the wrong thing. The exact results stay
        # served; only the suggestion is added. Bounded to small result
        # sets: the correction pass is an extra title scan. This
        # OVERRIDES the generic correction above when the served rows
        # are a poor match: the generic pass offers the served word
        # itself (`salary`, one edit from `salar`), which is no
        # correction at all — the poor-match pass excludes the served
        # words, so the next closest word (`salaar`) wins. When the
        # served rows are a good match (`avtar` → old `Avtar` rows,
        # correction `avatar`) `is_poor_match` is False and the generic
        # correction stands untouched.
        if (query and not work_ref and not exact_missed
                and 0 < total <= 500 and results):
            titles = [(item.get("clean_title") or item.get("title") or "")
                      for item in results]
            if works.is_poor_match(query, titles):
                did_you_mean_query = _poor_match_correction(conn, query, titles)
        total_pages = max(1, (total + limit - 1) // limit)
        answer = {
            "page": page,
            "limit": limit,
            "total": total,
            "total_pages": total_pages,
            "results": results,
            "fuzzy": fuzzy,
            "moods": mood_words,
            "mood_genres": mood_genres,
            "did_you_mean": did_you_mean_query,
            "suggestion": did_you_mean_query,
        }
        if suggestions is not None:
            answer["suggestions"] = suggestions
        return answer


def api_v1_get_trending(page: int = 1, limit: int = 20,
                        content_type: str = "", base_url: str = "") -> dict:
    """GET /api/v1/trending — the \"Most Sources\" rail as its own route.

    The order already exists as sort=trending on /api/v1/posts (most prints
    and mirrors — no play counts exist, so it is not popularity); this is
    the same page through a dedicated route, so the rail and any other
    consumer read one contract. Delegating keeps the 10 s deadline, the
    adult clause, the hides and the envelope identical to /api/v1/posts.
    `basis` says what the order is, so no client has to guess whether
    "trending" means views: it means most copies (`sort=most_copies`
    is the same order under its honest name).
    """
    answer = api_v1_get_posts(page=page, limit=limit, content_type=content_type,
                              sort="trending", base_url=base_url)
    answer["basis"] = "most_copies"
    answer["label"] = "Most copies"
    return answer


#: How long a grouped works list lives in-process. Grouping is a full
#: scan of the filtered post set plus a Python union-find; the catalog
#: changes only on batched merges, so a 120 s stale window on a browse
#: list is the right trade for not paying that scan on every page.
#: Keyed by the exact filter tuple (the candidate ids are a pure
#: function of the query, so they are not part of the key).
_WORKS_CACHE_TTL_SECONDS = 120.0
_WORKS_CACHE_MAX_ENTRIES = 32
_WORKS_LIST_CACHE: dict = {}

#: The columns the grouping scan needs: identity for `works.group_posts`
#: plus the display columns the representative is picked from. `slug`
#: and `source_site` are there for one server-side decision only — the
#: adult corroboration gate (`fast_fetch.adult_rule_agrees` reads the
#: row's own texts) — and never reach a response: the views drop them.
_WORKS_GROUP_COLS = (
    "p.id, p.clean_title, p.title, p.year, p.content_type, p.is_animated,"
    " p.imdb_id, p.tmdb_id, p.is_18_plus, p.poster_url, p.imdb_rating,"
    " p.genres, p.language, p.industry, p.country, p.slug, p.source_site,"
    " p.seasons"
)


def _adult_rule_agrees(row) -> bool:
    """The adult fold's corroboration gate, applied at read time to the
    works grouping: a flagged member hides its work only when the
    shared rule re-derives the flag from the row's own texts. A flag
    no rule can reproduce (a misflagged twin — Salaar carries one
    live) excludes that member but does not hide the work. The import
    is local, the way `_ensure_schema` does it: `fast_fetch` is the
    ledger module, not a route dependency."""
    import fast_fetch
    return fast_fetch.adult_rule_agrees(row)


def _works_cache_get(key):
    entry = _WORKS_LIST_CACHE.get(key)
    if entry is None:
        return None
    expires, value = entry
    if time.monotonic() > expires:
        del _WORKS_LIST_CACHE[key]
        return None
    return value


def _works_cache_put(key, value):
    if len(_WORKS_LIST_CACHE) >= _WORKS_CACHE_MAX_ENTRIES:
        oldest = min(_WORKS_LIST_CACHE,
                     key=lambda k: _WORKS_LIST_CACHE[k][0])
        del _WORKS_LIST_CACHE[oldest]
    _WORKS_LIST_CACHE[key] = (time.monotonic() + _WORKS_CACHE_TTL_SECONDS, value)


def _works_pick_representative(rows_by_id, post_ids):
    """The member post whose fields a work displays: has a poster, then
    has a rating, then the most canonical title (fewest clean-title
    tokens — the bare title beats its editioned copies, so the work
    reads `Salaar`, not `Salaar - 1 - Ceasefire`), then the lowest id.
    Deterministic; the work's numeric id stays the MINIMUM member post
    id regardless of who represents it."""
    best = None
    best_key = None
    for pid in post_ids:
        row = rows_by_id.get(int(pid))
        if row is None:
            continue
        tokens = works.work_title_tokens(
            row["clean_title"] or row["title"] or "")
        key = (1 if str(row["poster_url"] or "").strip() else 0,
               1 if str(row["imdb_rating"] or "").strip() else 0,
               -len(tokens),
               -int(pid))
        if best_key is None or key > best_key:
            best, best_key = row, key
    return best


def _works_best_rating(rows_by_id, post_ids):
    """The best-known rating of a work: the max parseable imdb_rating
    across its members, or None when no member carries one."""
    best = None
    for pid in post_ids:
        row = rows_by_id.get(int(pid))
        if row is None:
            continue
        try:
            value = float(str(row["imdb_rating"] or "").strip())
        except (TypeError, ValueError):
            continue
        if best is None or value > best:
            best = value
    return best


def _works_best_ids(rows_by_id, post_ids, rep_id=None):
    """The best-known external ids of a work: the representative's when
    it carries one, else the lowest-id member's. One member in ten
    carries an id (Salaar: 1 of 9 live) — the work's face is the bare
    title, which is usually the id-less copy, so the work would
    otherwise answer with no ids at all. Deterministic; ids are
    display data, never a grouping key here."""
    best_imdb = ""
    best_tmdb = None
    ordered = []
    if rep_id is not None:
        ordered.append(int(rep_id))
    ordered.extend(sorted(int(pid) for pid in post_ids
                          if rep_id is None or int(pid) != int(rep_id)))
    for pid in ordered:
        row = rows_by_id.get(int(pid))
        if row is None:
            continue
        if not best_imdb:
            try:
                best_imdb = (row["imdb_id"] or "").strip()
            except (KeyError, IndexError, TypeError):
                best_imdb = ""
        if best_tmdb in (None, "", 0):
            try:
                best_tmdb = row["tmdb_id"]
            except (KeyError, IndexError, TypeError):
                best_tmdb = None
        if best_imdb and best_tmdb not in (None, "", 0):
            break
    return best_imdb, best_tmdb


def _works_post_counts(conn, post_ids):
    """{post_id: (release_count, source_count, language)} for the given
    ids — the page's members only, never the whole catalog."""
    ids = [int(pid) for pid in post_ids]
    if not ids:
        return {}
    rows = conn.execute(
        "SELECT p.id, p.language,"
        " COUNT(DISTINCT r.id) as release_count,"
        " COUNT(DISTINCT s.id) as source_count"
        " FROM posts p"
        " LEFT JOIN releases r ON r.post_id = p.id"
        " LEFT JOIN download_sources s ON s.release_id = r.id"
        " WHERE p.id IN (" + ", ".join("?" for _ in ids) + ") GROUP BY p.id",
        ids).fetchall()
    return {int(r["id"]): (int(r["release_count"] or 0),
                           int(r["source_count"] or 0),
                           r["language"]) for r in rows}


def _works_enrich_page(conn, groups, base_url: str) -> list[dict]:
    """Project one page of grouped works in the posts list's shape.

    Each work is its representative post's `post_brief` item (same
    view, same art pair, same work handle, same subtitled flag), with
    `id` replaced by the work id (minimum member post id) and the
    work's own counts: `post_ids`, `post_count`, `release_count` /
    `source_count` summed over members, and `languages`, the union of
    the members' language buckets."""
    member_ids: list[int] = []
    for group in groups:
        member_ids.extend(group["post_ids"])
    counts = _works_post_counts(conn, member_ids)
    id_rows = conn.execute(
        "SELECT p.id, p.imdb_id, p.tmdb_id FROM posts p WHERE p.id IN ("
        + ", ".join("?" for _ in member_ids) + ")",
        member_ids).fetchall() if member_ids else []
    ids_by_id = {int(r["id"]): r for r in id_rows}
    rep_ids = sorted({int(g["rep_id"]) for g in groups})
    rep_rows = conn.execute(
        "SELECT " + _WORKS_GROUP_COLS + " FROM posts p WHERE p.id IN ("
        + ", ".join("?" for _ in rep_ids) + ")",
        rep_ids).fetchall() if rep_ids else []
    rep_by_id = {int(r["id"]): r for r in rep_rows}
    enriched = _enrich_post_rows(conn, [rep_by_id[i] for i in rep_ids
                                        if i in rep_by_id], base_url)
    enriched_by_id = {int(item["id"]): item for item in enriched}
    out = []
    for group in groups:
        item = enriched_by_id.get(int(group["rep_id"]))
        if item is None:
            continue
        item = dict(item)
        item["id"] = int(group["work_id"])
        item["post_ids"] = list(group["post_ids"])
        item["post_count"] = int(group["post_count"])
        release_count = 0
        source_count = 0
        buckets: set = set()
        for pid in group["post_ids"]:
            entry = counts.get(int(pid))
            if entry is None:
                continue
            release_count += entry[0]
            source_count += entry[1]
            buckets |= works.language_buckets(entry[2])
        item["release_count"] = release_count
        item["source_count"] = source_count
        item["languages"] = sorted(buckets)
        # The work's external ids come from its best-known member, not
        # only from the representative (which is usually the id-less
        # bare title): Salaar's ids live on 1 of its 9 posts.
        best_imdb, best_tmdb = _works_best_ids(
            ids_by_id, group["post_ids"], rep_id=int(group["rep_id"]))
        if best_imdb:
            item["imdb_id"] = best_imdb
        if best_tmdb not in (None, "", 0):
            item["tmdb_id"] = best_tmdb
        out.append(item)
    return out


def _works_sort_groups(groups, sort_key: str):
    """Order grouped works the way the posts list orders posts."""
    if sort_key == "rating":
        return sorted(groups,
                      key=lambda g: (-(g["best_rating"]
                                       if g["best_rating"] is not None else -1.0),
                                     -int(g["work_id"])))
    if sort_key == "title":
        return sorted(groups,
                      key=lambda g: (tuple(g["title_tokens"]), -int(g["work_id"])))
    if sort_key in ("trending", "most_copies"):
        return sorted(groups,
                      key=lambda g: (-int(g.get("copies") or 0),
                                     -int(g["work_id"])))
    if sort_key in ("", "newest"):
        def year_of(group):
            try:
                return int(group["year"])
            except (TypeError, ValueError):
                return 0
        return sorted(groups,
                      key=lambda g: (-year_of(g), -max(g["post_ids"])))
    return sorted(groups, key=lambda g: -int(g["work_id"]))


#: Cap on the detail group scan's trigram candidate set: under
#: SQLite's 999-variable cap with room for the query's other params.
#: A set that hits the cap falls back to the full LIKE scan.
_WORKS_GROUP_TRIGRAM_LIMIT = 900


def _works_title_candidate_ids(conn, token: str) -> list[int] | None:
    """Post ids sharing a 3-gram with `token`, or None to scan instead.

    The detail group scan's candidate pass (the fuzzy path's cure for
    the same cost class): the trigram index (`fts_posts_tri`) names
    every row sharing at least one of the token's 3-grams, best first.
    A row whose clean_title contains the token contains every gram,
    so the candidate set is a superset of the LIKE matches — unless
    it was truncated at the limit, in which case None says "scan the
    whole table instead" rather than risk dropping a member. None
    also when the index cannot answer (absent/empty on a pre-migration
    database): the LIKE scan is the exact fallback. An empty list is
    a real answer: no row shares a gram, so no row can contain the
    token. The limit stays under SQLite's 999-variable cap with room
    for the query's other params.
    """
    import search_fuzzy
    grams = search_fuzzy.candidate_grams(token)
    if not grams:
        return None
    ids = fts_posts.trigram_candidate_ids(
        conn, fts_posts.trigram_match(grams),
        _WORKS_GROUP_TRIGRAM_LIMIT)
    if ids is None or len(ids) >= _WORKS_GROUP_TRIGRAM_LIMIT:
        return None
    return ids


def _works_search_candidate_ids(conn, query: str) -> list[int]:
    """The post ids a works search query names, before grouping.

    THE swap point for search speed (user quality bar, 2026-11-12):
    every works search funnels through this one function, so the
    benchmark winner (FTS5, a title index, whatever the
    search-performance agent recommends) lands here and nowhere else
    — same contract in, same contract out: a query string in, the
    post ids it names literally out. The winner is FTS5
    (`fts_posts`): `token1 AND token2 AND ... AND last_token*` over
    `clean_title` + `cast_names`, so actor search keeps working and
    multi-word queries stay precise; a whole-word query (`the` must
    not match `other`) is one quoted token, which is the whole-word
    rule by construction — FTS5 tokenizes on word boundaries. A
    query with no tokens at all (empty / punctuation-only) answers
    [] without ever running a scan: that is the empty-query guard.
    No adult clause here — the grouping scan reads flagged rows
    deliberately and applies the work-level corroborated rule
    itself. The fuzzy fallback and the mood fallback live in the
    caller, not here: this is the literal pass only.

    When the FTS5 index is absent or empty (the migration has not
    built it on this database yet) the function falls back to the
    old literal match — whole-word title clause for a single
    stopword / 1–2 letter token, else the substring LIKE over
    title/slug/cast — so a pre-migration database answers exactly
    as it did before, only slower.
    """
    whole_word = works.is_whole_word_query(query)
    ids = fts_posts.search_candidate_ids(
        conn, query, whole_word=whole_word)
    if ids is not None:
        return ids
    if whole_word:
        clause, clause_params = works.whole_word_title_clause(query)
        rows = conn.execute(
            f"SELECT p.id FROM posts p WHERE {clause}",
            clause_params).fetchall()
    else:
        rows = conn.execute(
            "SELECT p.id FROM posts p WHERE"
            " (p.clean_title LIKE ? OR p.title LIKE ? OR p.slug LIKE ?"
            " OR p.cast_names LIKE ?)",
            [f"%{query}%"] * 4).fetchall()
    return [int(r["id"]) for r in rows]


def api_v1_get_works(query: str = "", content_type: str = "", page: int = 1,
                     limit: int = 20, full: bool = False,
                     base_url: str = "", industry: str = "", genre: str = "",
                     quality: str = "", sort: str = "", free_only: bool = False,
                     work_ref: str = "", language: str = "", region: str = "") -> dict:
    """GET /api/v1/works — one work per movie/series.

    The same envelope and the same query params as `/api/v1/posts`
    (plus `region=`, the alias for `industry=`), but the rows are
    grouped first (`works.group_posts`: fuzzy title + year, never ids
    alone) and the page is a page of WORKS. The adult rule is applied
    at work level, in the grouping: a group is dropped whole only
    when a flagged member's flag is corroborated
    (`fast_fetch.adult_rule_agrees` — the rule re-derived from the
    row's own texts). A flagged member that does not corroborate is
    excluded from the work but does not hide it — Salaar carries one
    such twin live. That is why the grouping scan reads flagged rows
    too instead of filtering them out first. A query matching only
    flagged rows answers an empty page, indistinguishable from no
    match.

    Search reuses the posts machinery exactly: the LIKE (actors
    included), the whole-word rule for single stopwords, the mood
    fallback, the one-edit fuzzy fallback, and `did_you_mean` — on a
    miss and, for small result sets, on a poor match. The grouped
    list is cached 120 s per filter tuple (see `_WORKS_CACHE_*`).
    `full` is accepted for signature parity with the posts route and
    ignored: the works list never publishes provenance in either mode.
    """
    _ensure_schema()
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 20
    limit = max(1, min(100, limit))
    offset = max(0, (page - 1) * limit)
    with get_db() as conn:
        deadline = time.monotonic() + SEARCH_DEADLINE_SECONDS

        def _search_deadline():
            return 1 if time.monotonic() > deadline else 0

        conn.set_progress_handler(_search_deadline, 1000)
        effective_industry = industry.strip() or region.strip()
        sort_key = sort.strip().lower()
        empty_page = {
            "page": page,
            "limit": limit,
            "total": 0,
            "total_pages": 1,
            "results": [],
            "fuzzy": False,
        }

        # A minted handle names one work: resolve it to its post, then
        # keep only the group holding that post. An unresolvable handle
        # answers an empty page, never an error.
        work_ref_post_id = None
        if work_ref:
            work_ref_post_id = _resolve_work_ref(conn, work_ref)
            if work_ref_post_id is None:
                return dict(empty_page)

        # Search candidates: the post ids the query names, before
        # grouping. None means "no title restriction" (no query, or a
        # mood query answered from genres instead).
        candidate_ids = None
        fuzzy = False
        did_you_mean_query = None
        mood_words = mood_search.moods_for_query(query) if query else []
        mood_genres = mood_search.genres_for_query(query) if query else []
        mood_clause = None
        mood_params: list = []
        exact_missed = False
        if query and not work_ref:
            candidate_ids = _works_search_candidate_ids(conn, query)
            exact_missed = not candidate_ids
            if exact_missed and mood_genres \
                    and not mood_search.strip_mood_words(query):
                # Pure mood query: answer from the genre facet, like the
                # posts route — no title restriction, a genre clause
                # instead.
                genre_clauses = []
                for mood_genre in mood_genres:
                    if mood_genre == "science fiction":
                        genre_clauses.append(
                            "(lower(p.genres) LIKE ? OR lower(p.genres) LIKE ?"
                            " OR lower(p.genres) LIKE ? OR lower(p.genres) LIKE ?)")
                        mood_params.extend(["%sci-fi%", "%sci fi%", "%scifi%",
                                            "%science fiction%"])
                    else:
                        genre_clauses.append("lower(p.genres) LIKE ?")
                        mood_params.append(f"%{mood_genre}%")
                mood_clause = "(" + " OR ".join(genre_clauses) + ")"
                candidate_ids = None
            elif exact_missed:
                fuzzy_ids = _fuzzy_post_ids(conn, query)
                if fuzzy_ids:
                    candidate_ids = fuzzy_ids
                    fuzzy = True
            if exact_missed:
                correction = did_you_mean.suggest_correction(conn, query)
                if correction is not None:
                    did_you_mean_query = correction["query"]

        cache_key = (query, content_type, effective_industry, genre,
                     language, quality, sort_key, free_only, work_ref)
        groups = _works_cache_get(cache_key)
        if groups is None:
            facet_clauses, facet_params = _facet_filter_clauses(
                content_type=content_type, industry=effective_industry,
                genre=genre, language=language, quality=quality,
                free_only=free_only)
            clauses = list(facet_clauses)
            params = list(facet_params)
            if mood_clause is not None:
                clauses.append(mood_clause)
                params.extend(mood_params)
            if candidate_ids is not None:
                if not candidate_ids:
                    # The title restriction names nothing: the grouping
                    # scan is skipped outright — there is no work to find.
                    groups = []
                else:
                    clauses.append("p.id IN (%s)"
                                   % ", ".join("?" for _ in candidate_ids))
                    params.extend(candidate_ids)
            if groups is None:
                hidden = panel_feed.hidden_work_ids()
                if hidden:
                    ids = sorted(hidden)[:panel_feed.HIDDEN_IDS_CAP]
                    clauses.append("p.id NOT IN (%s)"
                                   % ",".join("?" for _ in ids))
                    params.extend(ids)
                where_sql = " AND ".join(clauses) if clauses else "1 = 1"
                rows = conn.execute(
                    "SELECT " + _WORKS_GROUP_COLS + " FROM posts p"
                    f" WHERE {where_sql}", params).fetchall()
                rows_by_id = {int(r["id"]): r for r in rows}
                groups = [g for g in works.group_posts(
                              rows, adult_agrees=_adult_rule_agrees)
                          if not g["flagged"] and g["post_ids"]]
                if work_ref_post_id is not None:
                    groups = [g for g in groups
                              if work_ref_post_id in g["post_ids"]]
                for group in groups:
                    rep = _works_pick_representative(
                        rows_by_id, group["post_ids"])
                    group["rep_id"] = int(rep["id"]) \
                        if rep is not None else int(group["work_id"])
                    group["best_rating"] = _works_best_rating(
                        rows_by_id, group["post_ids"])
                if sort_key in ("trending", "most_copies"):
                    # The copies order needs counts for EVERY work, not
                    # just the page: one grouped query over the same
                    # filtered post set, via a subselect (no giant IN
                    # list), paid once per cache miss.
                    count_rows = conn.execute(
                        "SELECT r.post_id AS pid,"
                        " COUNT(DISTINCT r.id) AS rc,"
                        " COUNT(DISTINCT s.id) AS sc"
                        " FROM releases r"
                        " LEFT JOIN download_sources s ON s.release_id = r.id"
                        " WHERE r.post_id IN (SELECT p.id FROM posts p"
                        f" WHERE {where_sql}) GROUP BY r.post_id",
                        params).fetchall()
                    copies = {int(r["pid"]): int(r["rc"] or 0) + int(r["sc"] or 0)
                              for r in count_rows}
                    for group in groups:
                        group["copies"] = sum(
                            copies.get(int(pid), 0) for pid in group["post_ids"])
                groups = _works_sort_groups(groups, sort_key)
                _works_cache_put(cache_key, groups)
        total = len(groups)
        page_groups = groups[offset:offset + limit]
        if page_groups:
            results = _works_enrich_page(conn, page_groups, base_url)
        else:
            results = []
        # The typo case with hits, over work titles: the exact search
        # returned works, but none contains any query token exactly,
        # while a correction exists. Same bound as the posts route
        # (small result sets only — the correction is an extra scan).
        if (query and not work_ref and not exact_missed
                and did_you_mean_query is None and 0 < total <= 500
                and results):
            titles = [(item.get("clean_title") or item.get("title") or "")
                      for item in results]
            if works.is_poor_match(query, titles):
                did_you_mean_query = _poor_match_correction(conn, query, titles)
        suggestions = None
        if query and not work_ref and total == 0 and not fuzzy \
                and did_you_mean_query is None:
            suggestions = _newest_suggestions(conn, base_url)
        answer = {
            "page": page,
            "limit": limit,
            "total": total,
            "total_pages": max(1, (total + limit - 1) // limit),
            "results": results,
            "fuzzy": fuzzy,
            "moods": mood_words,
            "mood_genres": mood_genres,
            "did_you_mean": did_you_mean_query,
        }
        if suggestions is not None:
            answer["suggestions"] = suggestions
        return answer


def api_v1_get_work_detail(work_id, full: bool = False,
                           base_url: str = "", ladder: bool = True,
                           verify: bool = False) -> dict | None:
    """GET /api/v1/works/<id> — one work, every copy of it.

    `verify` is the serve-time verification rule (Player Fix v2): the
    HTTP route passes True, direct callers keep the unverified ladder.

    `<id>` is a post id: the work is the group holding it (the list
    `<id>` is a post id: the work is the group holding it (the list
    route's `id` is the minimum member post id). The response is the
    representative post's `post_detail` shape — same view, same art
    pair, same work handle — with the releases of EVERY member post
    merged in (`_fetch_releases_with_sources`, the post detail's own
    loader, so a work's print is its post's print), season/episode
    normalised to `S01`/`E01`, and the work's own keys: `post_ids`,
    `post_count`, `release_count`, `source_count`, `languages` (the
    members' language buckets), `episode_guide` (episodes 1..max per
    season with gaps marked, never the representative's `seasons`
    column), `is_ongoing`, and `latest_episode_added_at` (the newest
    release timestamp in the work — the new-episode signal a client
    diffs across polls; there is no snapshot table).

    A work answers None, exactly like a missing work, when a flagged
    member's flag is corroborated (`fast_fetch.adult_rule_agrees`):
    the flag belongs to the work, not to one row. A flagged member
    that does not corroborate is excluded from the work but does not
    hide it. That is stricter than `/api/v1/posts/<id>`, which still
    serves an unflagged twin per row — the fold migration will close
    that gap for posts; works does not wait for it.
    """
    _ensure_schema()
    try:
        seed_id = int(work_id)
    except (TypeError, ValueError):
        return None
    with get_db() as conn:
        seed = conn.execute(
            "SELECT * FROM posts WHERE id = ?", (seed_id,)).fetchone()
        if not seed or seed["is_18_plus"]:
            return None
        # The candidate set for this work's group: the same ids, or a
        # title sharing the first meaningful token, inside the year
        # window the merge allows. The title scan is a substring LIKE
        # over clean_title — the same cost class as the fuzzy candidate
        # pass — and the year window bounds it.
        tokens = works.work_title_tokens(seed["clean_title"] or seed["title"] or "")
        meaningful = [t for t in tokens if t not in works.STOPWORDS and len(t) >= 3]
        token = meaningful[0] if meaningful else (max(tokens, key=len) if tokens else "")
        try:
            year = int(seed["year"])
        except (TypeError, ValueError):
            year = None
        like_params: list = []
        like_sql = "1 = 0"
        if token:
            like_sql = "lower(p.clean_title) LIKE ?"
            like_params.append("%" + token + "%")
            if year is not None and 1900 <= year <= 2100:
                like_sql += (" AND (p.year IS NULL OR p.year = 0"
                             " OR p.year BETWEEN ? AND ?)")
                like_params.extend([year - 1, year + 1])
        imdb_id = (seed["imdb_id"] or "").strip()
        tmdb_id = seed["tmdb_id"]
        # The trigram candidate pass: the LIKE branch only runs over
        # rows sharing a 3-gram with the token (the fuzzy path's cure
        # for the same scan), so the group scan stops walking all
        # 224k posts. The imdb/tmdb branches are indexed equalities
        # and stay unrestricted. A None candidate set (no index, or
        # truncated) keeps the exact full scan — never a dropped
        # member for speed.
        like_ids = _works_title_candidate_ids(conn, token) if token else None
        if like_ids is not None:
            if like_ids:
                like_sql = (f"p.id IN ({', '.join('?' for _ in like_ids)})"
                            f" AND ({like_sql})")
                like_params = [int(pid) for pid in like_ids] + like_params
            else:
                # No row shares a gram with the token, so no row can
                # contain it: the LIKE branch matches nothing. (Not
                # reachable from a real seed — the seed's own title
                # contains the token — but `IN ()` is a syntax error,
                # so say so explicitly rather than building one.)
                like_sql = "1 = 0"
                like_params = []
        rows = conn.execute(
            "SELECT " + _WORKS_GROUP_COLS + " FROM posts p WHERE"
            " ((p.imdb_id = ? AND p.imdb_id <> '')"
            " OR (p.tmdb_id = ? AND p.tmdb_id IS NOT NULL)"
            f" OR ({like_sql}))",
            [imdb_id, tmdb_id if tmdb_id not in (None, "") else -1]
            + like_params).fetchall()
        groups = works.group_posts(rows, adult_agrees=_adult_rule_agrees)
        group = next((g for g in groups if seed_id in g["post_ids"]), None)
        if group is None:
            group = {"work_id": seed_id, "post_ids": [seed_id],
                     "flagged_ids": [], "flagged": False,
                     "title_tokens": tuple(tokens),
                     "year": str(year) if year else "ny", "post_count": 1}
        if group["flagged"] or not group["post_ids"]:
            return None
        member_ids = [int(pid) for pid in group["post_ids"]]
        member_rows = conn.execute(
            "SELECT " + _WORKS_GROUP_COLS + " FROM posts p WHERE p.id IN ("
            + ", ".join("?" for _ in member_ids) + ")",
            member_ids).fetchall()
        rows_by_id = {int(r["id"]): r for r in member_rows}
        rep = _works_pick_representative(rows_by_id, member_ids)
        if rep is None:
            return None
        rep_full = conn.execute(
            "SELECT * FROM posts WHERE id = ?", (int(rep["id"]),)).fetchone()
        if rep_full is None:
            return None
        if full:
            p_dict = dict(rep_full)
            p_dict["source_pages"] = [dict(r) for r in conn.execute(
                "SELECT source_site, url, source_title FROM post_sources WHERE post_id = ?",
                (int(rep["id"]),)).fetchall()]
        else:
            p_dict = redact.project(rep_full, "post_detail")
            p_dict.update(_art_pair(rep_full, base_url))
            p_dict["work_ref"] = _work_ref(rep_full)
        try:
            title = rep_full["clean_title"] or rep_full["title"] or ""
            work_type = catalog_v2.work_type_for(
                rep_full["content_type"] or "movie",
                int(rep_full["is_animated"] or 0), title)
            key = catalog_v2.work_key_for(
                title, rep_full["year"], work_type,
                rep_full["imdb_id"] or "", rep_full["tmdb_id"])
            work = conn.execute(
                "SELECT runtime_minutes FROM cat_works WHERE work_key = ?",
                (key,)).fetchone()
            if work is not None and work["runtime_minutes"]:
                p_dict["runtime_minutes"] = int(work["runtime_minutes"])
        except sqlite3.Error:
            pass
        release_rows, rel_list = _fetch_releases_with_sources(
            conn, member_ids, full=full, base_url=base_url)
        if not full:
            # One format for season/episode in this response: S01/E01.
            # The option-group scopes are normalised the same way, by
            # passing normalised release rows to `_option_groups` — it
            # groups by (season, episode), so normalising first is what
            # folds `1` and `S01` into one scope.
            norm_releases = []
            for rel_row, r_dict in zip(release_rows, rel_list):
                season = works.parse_season(rel_row["season"])
                episode = works.parse_episode(rel_row["episode"])
                r_dict["season"] = works.format_season(season) if season else None
                r_dict["episode"] = works.format_episode(episode) if episode else None
                norm = dict(rel_row)
                norm["season"] = r_dict["season"]
                norm["episode"] = r_dict["episode"]
                norm_releases.append(norm)
            p_dict["option_groups"] = (_option_groups(norm_releases, rel_list, verify=verify)
                                       if ladder else [])
        p_dict["releases"] = rel_list
        p_dict["id"] = int(group["work_id"])
        p_dict["post_ids"] = member_ids
        p_dict["post_count"] = len(member_ids)
        p_dict["release_count"] = len(release_rows)
        p_dict["source_count"] = sum(len(r.get("sources") or [])
                                     for r in rel_list)
        buckets: set = set()
        for row in member_rows:
            buckets |= works.language_buckets(row["language"])
        p_dict["languages"] = sorted(buckets)
        # Best-known external ids, as on the list: the representative
        # is usually the id-less bare title, while one member in ten
        # carries the IMDb/TMDb id (Salaar: 1 of 9 live).
        best_imdb, best_tmdb = _works_best_ids(
            rows_by_id, member_ids, rep_id=int(rep["id"]))
        if best_imdb:
            p_dict["imdb_id"] = best_imdb
        if best_tmdb not in (None, "", 0):
            p_dict["tmdb_id"] = best_tmdb
        seasons, latest = works.build_seasons(release_rows)
        p_dict["episode_guide"] = seasons
        # A "new episode" signal is meaningless for a film: the field
        # answers None unless some member is a series.
        has_series = any((row["content_type"] or "") in
                         ("series", "ongoing_season") for row in member_rows)
        p_dict["latest_episode_added_at"] = latest if has_series else None
        p_dict["is_ongoing"] = any(
            (row["content_type"] or "") == "ongoing_season"
            or works.title_marks_ongoing(row["clean_title"] or row["title"] or "")
            for row in member_rows)
        art: list = []
        seen = set()
        for pid in member_ids:
            for entry in _season_artwork(conn, pid):
                marker = (entry["kind"], entry["season"], entry["episode"],
                          entry["url"])
                if marker in seen:
                    continue
                seen.add(marker)
                art.append(entry)
        art.sort(key=lambda e: (e["season"],
                                0 if e["kind"] == "season_poster" else 1,
                                e["episode"]))
        p_dict["season_artwork"] = art
        if verify and not full:
            # Serve-time verification is on: kick the all-band
            # re-verification in the background, unreported — the next
            # press answers from what it banks.
            _preresolve_for_detail(p_dict)
        return p_dict


def api_v1_get_related(work_id, page: int = 1, limit: int = 20,
                       base_url: str = "") -> dict:
    """GET /api/v1/related?work_id= — \"Because you watch\".

    `work_id` is a v1 post id. A seed that is missing or adult answers an
    empty page (total 0), never an error — the rail hides instead of
    failing the Home load. A non-integer work_id raises ValueError; the
    route turns that into a 400. The score is the seed's own evidence:
    a shared cast member +5 each, a shared genre +3 each, the same
    industry +1, the same content type +1, a year within two +1; the
    order is score, then the same (release_count + source_count) the
    trending rail uses, then id. Only rows with a score above zero are
    returned, so a seed with no neighbours answers empty instead of the
    whole catalog in disguise. The adult clause and the panel hides
    apply exactly as on /api/v1/posts.
    """
    try:
        seed_id = int(work_id)
    except (TypeError, ValueError):
        raise ValueError("work_id must be an integer post id")
    _ensure_schema()
    try:
        page = int(page)
    except (TypeError, ValueError):
        page = 1
    page = max(1, page)
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 20
    limit = max(1, min(100, limit))
    offset = max(0, (page - 1) * limit)
    empty = {"page": page, "limit": limit, "total": 0,
             "total_pages": 1, "results": []}
    with get_db() as conn:
        deadline = time.monotonic() + SEARCH_DEADLINE_SECONDS

        def _related_deadline():
            return 1 if time.monotonic() > deadline else 0

        conn.set_progress_handler(_related_deadline, 1000)
        seed = conn.execute(
            "SELECT id, genres, cast_names, industry, content_type, year,"
            " is_18_plus FROM posts WHERE id = ?",
            (seed_id,)).fetchone()
        if seed is None or seed["is_18_plus"]:
            return empty
        # The score, as one expression over the seed's own fields. Genre
        # and cast tokens are capped at five each: a long cast list must
        # not drown the other signals, and every token is escaped before
        # it reaches the LIKE pattern.
        score_parts = []
        score_params = []
        for token in _genre_tokens(seed["genres"])[:5]:
            score_parts.append(
                r"(CASE WHEN lower(p.genres) LIKE ? ESCAPE '\' THEN 3 ELSE 0 END)")
            score_params.append("%" + _like_escape(token) + "%")
        for name in _genre_tokens(seed["cast_names"])[:5]:
            score_parts.append(
                r"(CASE WHEN lower(p.cast_names) LIKE ? ESCAPE '\' THEN 5 ELSE 0 END)")
            score_params.append("%" + _like_escape(name) + "%")
        industry_tokens = _genre_tokens(seed["industry"])
        if industry_tokens:
            score_parts.append(
                r"(CASE WHEN lower(p.industry) LIKE ? ESCAPE '\' THEN 1 ELSE 0 END)")
            score_params.append("%" + _like_escape(industry_tokens[0]) + "%")
        if seed["content_type"]:
            score_parts.append("(CASE WHEN p.content_type = ? THEN 1 ELSE 0 END)")
            score_params.append(seed["content_type"])
        try:
            seed_year = int(seed["year"]) if seed["year"] is not None else None
        except (TypeError, ValueError):
            seed_year = None
        if seed_year is not None:
            score_parts.append(
                "(CASE WHEN p.year BETWEEN ? AND ? THEN 1 ELSE 0 END)")
            score_params.extend([seed_year - 2, seed_year + 2])
        score_sql = " + ".join(score_parts) if score_parts else "0"
        where_clauses = [redact.adult_clause("p"), "p.id != ?"]
        where_params = [seed_id]
        hidden = panel_feed.hidden_work_ids()
        if hidden:
            ids = sorted(hidden)[:panel_feed.HIDDEN_IDS_CAP]
            where_clauses.append(
                "p.id NOT IN (%s)" % ",".join("?" for _ in ids))
            where_params.extend(ids)
        where_sql = " AND ".join(where_clauses)
        total = conn.execute(
            "SELECT COUNT(*) FROM (SELECT p.id, (" + score_sql + ") AS _rel_score"
            " FROM posts p WHERE " + where_sql + ") WHERE _rel_score > 0",
            score_params + where_params).fetchone()[0]
        if total == 0:
            return empty
        page_sql = (
            "SELECT p.id, p.clean_title, p.title, p.year, p.content_type,"
            " p.seasons, p.poster_url, p.backdrop_urls, p.imdb_rating,"
            " p.imdb_id, p.tmdb_id, p.genres, p.is_animated, p.industry,"
            " p.country, p.language, (" + score_sql + ") AS _rel_score,"
            " COUNT(DISTINCT r.id) as release_count,"
            " COUNT(DISTINCT s.id) as source_count"
            " FROM posts p"
            " LEFT JOIN releases r ON r.post_id = p.id"
            " LEFT JOIN download_sources s ON s.release_id = r.id"
            " WHERE " + where_sql + " GROUP BY p.id"
            " HAVING _rel_score > 0"
            " ORDER BY _rel_score DESC,"
            " (release_count + source_count) DESC, p.id DESC"
            " LIMIT ? OFFSET ?")
        rows = conn.execute(
            page_sql,
            score_params + where_params + [limit, offset]).fetchall()
        # Audit #17: one row per work in the rail; `total` still counts
        # rows (see _dedupe_page_rows).
        rows = _dedupe_page_rows(rows)
        return {
            "page": page,
            "limit": limit,
            "total": total,
            "total_pages": max(1, (total + limit - 1) // limit),
            "results": _enrich_post_rows(conn, rows, base_url),
        }


def api_v1_get_facets() -> dict:
    """GET /api/v1/facets — the browse jump-off chips.

    Four groups, each entry {key, label, count}: genres (the 10 panel
    categories), languages (top 12), industries (the 5 fixed keys), types
    (the content_type values). Every count is the number of public,
    non-adult posts the matching filter returns — the counts and the
    filters share the same predicates (`GENRE_FILTER_SQL`,
    `INDUSTRY_FILTER_SQL`, the `language=` LIKE), so a chip's count is
    what its tap delivers. The panel hides apply here too. A group with
    no rows is an empty list, never an error.
    """
    _ensure_schema()
    with get_db() as conn:
        deadline = time.monotonic() + SEARCH_DEADLINE_SECONDS

        def _facets_deadline():
            return 1 if time.monotonic() > deadline else 0

        conn.set_progress_handler(_facets_deadline, 1000)
        adult = redact.adult_clause("p")
        hidden = panel_feed.hidden_work_ids()
        hidden_sql = ""
        hidden_params: list = []
        if hidden:
            ids = sorted(hidden)[:panel_feed.HIDDEN_IDS_CAP]
            hidden_sql = " AND p.id NOT IN (%s)" % ",".join("?" for _ in ids)
            hidden_params = ids
        # Genres + industries: one aggregate, one CASE per key, so the
        # whole catalog is scanned once for both groups.
        cases = []
        case_params: list = []
        for key in GENRE_KEYS:
            frag, params = GENRE_FILTER_SQL[key]
            cases.append("SUM(CASE WHEN %s THEN 1 ELSE 0 END) AS %s"
                         % (frag, key.replace("-", "_")))
            case_params.extend(params)
        for key in INDUSTRY_KEYS:
            cases.append("SUM(CASE WHEN %s THEN 1 ELSE 0 END) AS %s"
                         % (INDUSTRY_FILTER_SQL[key], key))
        agg = conn.execute(
            "SELECT %s FROM posts p WHERE %s%s"
            % (", ".join(cases), adult, hidden_sql),
            case_params + hidden_params).fetchone()
        genres = [{"key": key, "label": key.title(),
                   "count": int(agg[key.replace("-", "_")] or 0)}
                  for key in GENRE_KEYS]
        industries = [{"key": key, "label": INDUSTRY_LABELS[key],
                       "count": int(agg[key] or 0)}
                      for key in INDUSTRY_KEYS]
        # Languages: group by the raw value, then split multi-language
        # rows in Python — a Hindi+English post counts for both, the same
        # rows a `language=` filter matches.
        lang_counts: dict[str, int] = {}
        lang_rows = conn.execute(
            "SELECT p.language, COUNT(*) AS c FROM posts p"
            " WHERE %s%s GROUP BY p.language ORDER BY c DESC LIMIT 40"
            % (adult, hidden_sql), hidden_params).fetchall()
        for raw, count in lang_rows:
            for token in _genre_tokens(raw):
                lang_counts[token] = lang_counts.get(token, 0) + int(count)
        languages = [{"key": key, "label": key.title(), "count": count}
                     for key, count in sorted(
                         lang_counts.items(), key=lambda kv: -kv[1])[:12]]
        # Types: the content_type values the ledger actually writes.
        types = [{"key": ctype or "",
                  "label": TYPE_LABELS.get(
                      ctype or "", (ctype or "").replace("_", " ").title()),
                  "count": int(count)}
                 for ctype, count in conn.execute(
                     "SELECT p.content_type, COUNT(*) AS c FROM posts p"
                     " WHERE %s%s GROUP BY p.content_type ORDER BY c DESC"
                     % (adult, hidden_sql), hidden_params).fetchall()
                 if ctype]
        return {"genres": genres, "languages": languages,
                "industries": industries, "types": types}


def api_v1_search_by_media(query: str = "", duration_s=None, resolution: str = "",
                           audio_language: str = "", limit: int = 10,
                           full: bool = False, base_url: str = "",
                           sort: str = "best") -> dict:
    """/api/v1/search/by-media — what the file in the viewer's hand probably is.

    Thin on purpose: the matching and the three-way honesty report live in
    `media_search`. This function only supplies what that module cannot own — the
    artwork handles, the account-surface work reference and the subtitled flag —
    through the same `_art_pair` / `_work_ref` / `_subtitled_posts` every other v1
    list already uses, so a by-media row and a `q=` row are indistinguishable
    shapes to the client. `subtitled` is filled here rather than in `media_search`
    because it is a display-surface verdict, and that module answers matching.
    """
    _ensure_schema()

    def enrich(item, row):
        item.update(_art_pair(row, base_url))
        item["work_ref"] = _work_ref(row)

    with get_db() as conn:
        result = media_search.search_by_media(
            conn, title=query, duration_s=duration_s, resolution=resolution,
            audio_language=audio_language, limit=limit, full=full, enrich=enrich,
            sort=sort)
        if not full and result.get("results"):
            subs = _subtitled_posts(conn, [int(r["id"]) for r in result["results"]])
            for item in result["results"]:
                item["subtitled"] = bool(subs.get(int(item["id"]), False))
        return result


_SOURCE_SERVICE_RANK = {"pixeldrain": 1, "vegadrive": 2, "hubcloud_10g": 3,
                        "fsl_r2": 4, "fastdl": 5, "google_cdn": 6}


def _source_ladder_key(s):
    """The evidence ladder as a sort key — the same order the per-release
    query's ORDER BY used to give, now applied in Python over one
    batched fetch: a probe-confirmed live copy (0), then an unprobed
    claim (1), then expired (2), then dead last (3); then
    non-temporary before temporary (SQL ASC puts NULL first); then the
    server preference. Stable sort over id-ordered input keeps ties in
    the order the old query returned them.
    """
    status = s["status"]
    if status in ("dead", "broken", "gone", "quarantined"):
        rank = 3
    elif status == "expired":
        rank = 2
    elif (status == "active" and s["last_checked_at"] is not None
          and s["http_status"] is not None and s["http_status"] != 0):
        rank = 0
    else:
        rank = 1
    temp = s["is_temporary"]
    return (rank, (temp is not None, temp or 0),
            _SOURCE_SERVICE_RANK.get(s["service"], 99))


def _fetch_releases_with_sources(conn, post_ids, full: bool = False,
                                 base_url: str = ""):
    """The releases of one or more posts, with their sources, in the
    post detail's own shape. Shared by `/api/v1/posts/<id>` (one post)
    and `/api/v1/works/<id>` (every member post of a work): the source
    order is the same evidence ladder in both — a probe-confirmed live
    copy, then an unprobed claim, then expired, then dead last — and
    the projection is the same (`release` view + `link_view`), so a
    work's print is indistinguishable from its post's print. Returns
    (release_rows, rel_list), ordered by post id, then release id. The
    sources come in one query for all releases (the old code asked
    once per release — 109 queries for a 109-release work) and are
    grouped and ladder-sorted in Python."""
    ids = [int(pid) for pid in post_ids]
    if not ids:
        return [], []
    releases = conn.execute(
        "SELECT * FROM releases WHERE post_id IN ("
        + ", ".join("?" for _ in ids) + ") ORDER BY post_id ASC, id ASC",
        ids).fetchall()
    rel_ids = [int(rel["id"]) for rel in releases]
    sources_by_rel: dict[int, list] = {rid: [] for rid in rel_ids}
    if rel_ids:
        for s in conn.execute(
                "SELECT * FROM download_sources WHERE release_id IN ("
                + ", ".join("?" for _ in rel_ids)
                + ") ORDER BY release_id ASC, id ASC",
                rel_ids).fetchall():
            sources_by_rel[int(s["release_id"])].append(s)
    rel_list = []
    for rel in releases:
        sources = sorted(sources_by_rel[int(rel["id"])],
                         key=_source_ladder_key)
        # The ordering above is our own preference between servers; it is a
        # query, not a field. Nothing that names a hoster leaves this box.
        # The first key is audit critical 10's evidence ladder — a probe-
        # confirmed live copy, then an unprobed claim (unchecked, never a
        # promise), then expired, then dead last. `status = 'active' DESC`
        # alone ranked a scraper's blanket 'active' above everything, dead
        # links included.
        if full:
            r_dict = dict(rel)
            r_dict["sources"] = [dict(s) for s in sources]
        else:
            r_dict = redact.project(rel, "release")
            r_dict["label"] = redact.public_label(rel)
            r_dict["sources"] = [link_view(s, base_url) for s in sources]
        rel_list.append(r_dict)
    return releases, rel_list


def api_v1_get_post_detail(post_id: int, full: bool = False,
                           base_url: str = "", ladder: bool = True,
                           warm: bool = False, vip: bool = False,
                           audio: str = "", verify: bool = False) -> dict | None:
    """GET /api/v1/posts/<id> — one post, every copy of it.

    `verify` is the serve-time verification rule (Player Fix v2): the
    HTTP route passes True, direct callers keep the unverified ladder.
    When it is on, the detail open also kicks the async all-band
    re-verification, whether or not `?warm=1` was asked for.
    """
    _ensure_schema()
    with get_db() as conn:
        post = conn.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
        if not post or post["is_18_plus"]:
            return None
        if full:
            p_dict = dict(post)
            p_dict["source_pages"] = [dict(r) for r in conn.execute(
                "SELECT source_site, url, source_title FROM post_sources WHERE post_id = ?",
                (post_id,)
            ).fetchall()]
        else:
            p_dict = redact.project(post, "post_detail")
            p_dict.update(_art_pair(post, base_url))
            p_dict["work_ref"] = _work_ref(post)

        # Runtime comes from the v2 work row, keyed exactly the way
        # `_work_ref` derives it — a post with no matching work simply has
        # no runtime, and the app shows nothing rather than a guessed one.
        try:
            title = post["clean_title"] or post["title"] or ""
            work_type = catalog_v2.work_type_for(
                post["content_type"] or "movie", int(post["is_animated"] or 0), title)
            key = catalog_v2.work_key_for(
                title, post["year"], work_type, post["imdb_id"] or "", post["tmdb_id"])
            work = conn.execute(
                "SELECT runtime_minutes FROM cat_works WHERE work_key = ?",
                (key,)).fetchone()
            if work is not None and work["runtime_minutes"]:
                p_dict["runtime_minutes"] = int(work["runtime_minutes"])
        except sqlite3.Error:
            pass

        releases, rel_list = _fetch_releases_with_sources(
            conn, [post_id], full=full, base_url=base_url)
        if not full:
            p_dict["option_groups"] = (
                _option_groups(releases, rel_list, vip=vip,
                               audio_languages=_split_audio_param(audio),
                               verify=verify)
                if ladder else [])
        p_dict["season_artwork"] = _season_artwork(conn, post_id)
        p_dict["releases"] = rel_list
        if warm and not full:
            # The detail screen opens long before Play is pressed: warming
            # the auto tier now means the press answers from the resolved
            # cache instead of paying a live 5–11 s resolve under the player.
            p_dict["preresolve"] = _preresolve_for_detail(p_dict)
        elif verify and not full:
            # Serve-time verification is on: kick the same all-band
            # re-verification in the background, unreported — the next
            # press answers from what it banks.
            _preresolve_for_detail(p_dict)
        return p_dict


def _verify_tier_link(link, conn, *, live: bool = True):
    """Verify one ladder candidate; the default `_option_groups` verifier.

    Cached-first (research fold-in §1): the ledger row's own measured
    verdict (active + HTTP 200–399 within the hot TTL) serves without a
    probe, and a fresh banked resolution inside `verify_candidate` does
    the same. Only a never-checked (or stale) candidate pays a live
    re-resolve + final-file probe. Returns a result dict
    ``{verified, reason, verified_at, source_id, evidence}``; failure
    evidence is returned, NOT written — `_verify_option_tiers` applies
    the poison-cache guard first and records afterwards.

    `live=False` is the detail fast path: cached verdicts only, never
    a network probe. A candidate with no cached verdict answers
    ``unchecked`` (keepable — its band stays, the press re-verifies
    live), and one whose ledger row is already dead answers ``dead``
    (a band of nothing but dead links is hidden). The live pass is
    the detail routes' `_preresolve_for_detail` warm (background
    threads, banks via `_resolve_and_bank`) and the press-time
    re-verify — never this call.
    """
    import serve_verify
    try:
        source_id = redact.parse_token(link.get("stream_id") or "",
                                       signing_secret(), signed_only=True)
    except Exception:      # noqa: BLE001 — an unparseable handle is unavailable
        return {"verified": False, "reason": "unparseable", "source_id": None}
    if not source_id:
        return {"verified": False, "reason": "unparseable", "source_id": None}
    source_id = int(source_id)
    if conn is not None:
        try:
            row = conn.execute(
                "SELECT status, http_status, last_checked_at FROM download_sources"
                " WHERE id = ?", (source_id,)).fetchone()
        except sqlite3.Error:
            row = None
        if row is not None:
            cached = {"status": row[0], "http_status": row[1],
                      "last_checked_at": row[2]}
            if serve_verify.is_known_good(cached):
                stamp = serve_verify._epoch_of(cached["last_checked_at"])
                return {"verified": True, "reason": "cached",
                        "verified_at": stamp, "source_id": source_id}
            if not live and str(row[0] or "").lower() in serve_verify.DEAD_STATES:
                return {"verified": False, "reason": "dead",
                        "source_id": source_id}
    result = serve_verify.verify_candidate(
        source_id, resolver=_resolve_coalesced, conn=conn,
        record_evidence=False, live=live)
    result["source_id"] = source_id
    return result


def _verify_tier_link_cached(link, conn):
    """The detail fast path's verifier: cached verdicts only, no network.

    `_option_groups` answers from this synchronously; the live pass
    (`_verify_tier_link`, live=True) runs at press time and in the
    detail routes' `_preresolve_for_detail` warm.
    """
    return _verify_tier_link(link, conn, live=False)


def _source_host(conn, stream_id: str) -> str:
    """The bridge host behind a ladder handle, for host-priority ordering.

    The projected link never carries a host (provenance); the ledger row
    does. An unparseable handle or a missing row answers "" (neutral).
    """
    try:
        source_id = redact.parse_token(stream_id or "", signing_secret(),
                                       signed_only=True)
    except Exception:      # noqa: BLE001 — an unparseable handle is unavailable
        return ""
    if not source_id or conn is None:
        return ""
    try:
        row = conn.execute("SELECT source_url FROM download_sources"
                           " WHERE id = ?", (int(source_id),)).fetchone()
    except sqlite3.Error:
        return ""
    if row is None:
        return ""
    try:
        import urllib.parse
        return urllib.parse.urlsplit(str(row[0] or "")).netloc.lower()
    except ValueError:
        return ""


def _verify_option_tiers(tier_rows, *, timeout: float = 10.0,
                         verifier=None, conn=None, host_of=None):
    """Verify every tier's candidates; hide bands with no verified link
    and no unchecked candidate.

    All candidates (top 3 per band, across all bands) probe concurrently
    under one `timeout` deadline — the wait is ~one probe, not the sum.
    Candidates are ordered by measured host priority first (best/
    most-active hosts first, weak hosts last, unmeasured neutral — the
    user-ordered host ranking), then by their existing score order, so
    the first verified candidate in that order wins the band. Returns
    ``(kept_tiers, poisoned)``. When the batch is poisoned (over half
    the candidates got no answer at all) the ladder is returned
    unchanged and nothing is recorded. Otherwise failure evidence is
    recorded for every failed candidate, the first verified candidate
    wins its band (stamped `verified_at`), verified runners-up stay as
    backups, and a band with no verified candidate is dropped — unless
    a candidate in it is merely ``unchecked`` (no cached verdict either
    way, e.g. the detail fast path's cached-only pass): an unchecked
    candidate keeps its band, because it is not known dead, only never
    checked, and the press re-verifies it live before serving bytes.
    A band whose candidates are all hard-failed (or timed out with no
    answer at all) is still hidden.
    """
    import concurrent.futures
    import serve_verify
    verify = verifier or _verify_tier_link

    def _candidates(tier) -> list:
        seen: set = set()
        out = []
        for item in [tier.get("link")] + list(tier.get("backups") or []):
            if not isinstance(item, dict):
                continue
            stream_id = item.get("stream_id")
            if not stream_id or stream_id in seen:
                continue
            seen.add(stream_id)
            out.append(item)
        return out[:serve_verify.VERIFY_CANDIDATES_PER_BAND]

    def _host_score(link) -> float:
        if conn is None:
            return serve_verify.HOST_UNMEASURED_RANK
        try:
            host = host_of(link) if host_of is not None \
                else _source_host(conn, link.get("stream_id") or "")
        except Exception:      # noqa: BLE001 — a host lookup fault is neutral
            host = ""
        return serve_verify.host_rank_score(conn, host)

    by_tier = []
    for tier in tier_rows:
        candidates = _candidates(tier)
        ranked = sorted(enumerate(candidates),
                        key=lambda pair: (-_host_score(pair[1]), pair[0]))
        by_tier.append([link for _index, link in ranked])
    jobs = [(tier_index, rank, link)
            for tier_index, candidates in enumerate(by_tier)
            for rank, link in enumerate(candidates)]
    if not jobs:
        return list(tier_rows), False
    results: dict = {}
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=8)
    try:
        futures = {pool.submit(verify, link, conn): (tier_index, rank)
                   for tier_index, rank, link in jobs}
        done, _pending = concurrent.futures.wait(
            list(futures), timeout=float(timeout))
        for future in done:
            try:
                results[futures[future]] = future.result()
            except Exception:      # noqa: BLE001 — a verifier fault is transport
                results[futures[future]] = {"verified": False,
                                            "reason": "transport"}
    finally:
        # Stragglers keep resolving in their threads (their answers are
        # banked by the resolver path); the response must not wait for them.
        pool.shutdown(wait=False, cancel_futures=True)
    no_answer = 0
    for tier_index, rank, _link in jobs:
        result = results.get((tier_index, rank))
        if result is None:
            no_answer += 1
        elif not result.get("verified") \
                and str(result.get("reason") or "") \
                in serve_verify.NO_ANSWER_REASONS:
            no_answer += 1
    if no_answer / len(jobs) > serve_verify.POISON_NO_ANSWER_FRACTION:
        return list(tier_rows), True
    # The batch is real evidence: record every failure now (the guard ran).
    if conn is not None:
        for _key, result in sorted(results.items()):
            evidence = (result or {}).get("evidence")
            if evidence:
                serve_verify.record_probe_failure(
                    conn, int(evidence["source_id"]),
                    str(evidence["reason"]),
                    http_status=int(evidence.get("http_status") or 0),
                    final_url=str(evidence.get("final_url") or ""))
    kept = []
    for tier_index, tier in enumerate(tier_rows):
        verified = []
        unchecked = []
        for rank, link in enumerate(by_tier[tier_index]):
            result = results.get((tier_index, rank))
            if result and result.get("verified"):
                link["verified_at"] = result.get("verified_at") or time.time()
                verified.append(link)
            elif result and str(result.get("reason") or "") == "unchecked":
                # No cached verdict either way — not known dead, only
                # never checked. It keeps its band; a verified candidate
                # still wins the band outright, and the press re-verifies
                # an unchecked winner live before serving bytes.
                unchecked.append(link)
        ordered = verified + unchecked
        if not ordered:
            continue
        tier["link"] = ordered[0]
        tier["backups"] = ordered[1:1 + tiers.BACKUP_LIMIT]
        kept.append(tier)
    return kept, False


def _option_groups(releases, rel_list, *, vip: bool = False,
                   audio_languages=(), verify: bool = False,
                   verify_timeout: float = 10.0,
                   _verifier=None, _host_of=None) -> list:
    """One best and fastest copy per quality band, for the player and the card.

    `verify` is the Player Fix v2 serve-time rule (diagnosis §6.2 as refined
    by the research fold-in), split for speed: the response answers from
    cached verdicts only — a fresh banked resolution or a measured-active
    verdict inside the hot TTL stamps the winner `verified_at` at once —
    and never waits on a live probe, so a cold title opens in under a
    second instead of paying the whole 10 s verify batch. Warming is the
    detail routes' `_preresolve_for_detail`: after the response is built
    it resolves each band's winner in a background thread and banks the
    success, so the next open / Play press finds it warm. (A separate
    background batch used to run here too; it was removed — it verified
    every candidate including backups, banked nothing, and left the
    cache exactly as it found it, while burning a 10 s thread per detail
    call on a 1-vCPU box.) The first verified candidate wins its band —
    ordered by measured host priority first (best/most-active hosts first,
    weak hosts last; user-ordered host ranking, seeded from a link check) —
    and a band with no verified candidate is hidden only when every
    candidate in it is known-dead from cache; an unchecked candidate
    keeps its band, because it is not known dead, only never checked.
    The served link carries a `verified_at` stamp when one exists.
    Gated tiers are verified the same way — a VIP press gets a working
    link too — and an unverified gated tier is hidden rather than served
    dead. The rule that only verified links play is enforced where bytes
    are served: `/api/v1/stream` re-verifies live at press time and
    refuses a dead or stale link. `verify` defaults off: direct callers
    (tests, offline builders) keep the unverified ladder; the HTTP
    detail routes pass True.

    The cached pass never lets a detail call hang: it reads the ledger
    only, and a poisoned batch (over half the candidates with no answer
    at all — our network is down, not the internet) leaves the ladder
    untouched and records nothing.

    The ledger holds up to six copies of the same print on six servers; a viewer
    wants one row per quality (the owner's "Auto default + visible quality
    switch"), and so does the download card. The candidates arrive already
    ordered by the server preference the healers earned, which is a *sort key*
    and never a field, so the winner is chosen without publishing who serves it.

    Releases are grouped by their own season/episode scope: a series must not
    offer S02E05's 1080p copy when the user is playing S01E01.

    Audit #1/#32 — the ladder the app's Play button follows:
    * ``gated``: a 1080p/2160p tier is premium. A free viewer who presses it
      gets a 402 and a stuck spinner, so gated tiers sort AFTER every free
      tier and ``auto`` never points at one — the player starts at the best
      free copy it can actually play. The tier still travels (marked), so
      the quality switch can offer the VIP upsell instead of hiding the band.
    * ``preferred_audio``: when the caller names its preferred audio (the
      ``?audio=`` detail parameter, from the region the user picked),
      tiers carrying it sort first within their gate class and ``auto``
      prefers them — a Desi viewer starts on a Hindi print, not a Telugu one.
    """
    scopes: dict = {}
    for rel, r_dict in zip(releases, rel_list):
        scopes.setdefault((rel["season"], rel["episode"]), []).append(r_dict)
    wanted_audio = {str(a).strip().lower()
                    for a in (audio_languages or []) if str(a).strip()}
    groups = []
    for (season, episode), prints in scopes.items():
        ladders = []
        for r_dict in prints:
            ladder = tiers.for_release(r_dict, r_dict.get("sources") or [])
            band = ladder["tiers"][0]["band"] if ladder["tiers"] else tiers.UNSPECIFIED
            r_dict["band"] = band
            r_dict["quality_label"] = (ladder["tiers"][0]["label"]
                                       if ladder["tiers"] else "Available")
            if ladder["tiers"]:
                ladders.append(ladder)
        merged = tiers.merge(ladders)
        if merged["tiers"]:
            if verify:
                # Player Fix v2 serve-time rule, split for speed: the
                # response answers from cached verdicts only (never a
                # live probe — a cold title used to wait out the whole
                # 10 s verify batch before the app saw it), so the
                # ladder and `auto` agree on the best cached winner.
                # Warming is the detail routes' `_preresolve_for_detail`
                # (background threads, banks successes); a band is
                # hidden only on cached hard evidence, an unchecked
                # candidate keeps its band, and the press re-verifies
                # it live before serving bytes.
                with get_db() as _verify_conn:
                    merged["tiers"], _poisoned = _verify_option_tiers(
                        merged["tiers"], timeout=verify_timeout,
                        verifier=_verifier or _verify_tier_link_cached,
                        conn=_verify_conn, host_of=_host_of)
                if not merged["tiers"]:
                    continue
            for tier in merged["tiers"]:
                tier["gated"] = bool(
                    tier["band"] in GATED_QUALITY_BANDS and not vip)
                tier["preferred_audio"] = bool(
                    wanted_audio and any(
                        str(lang).strip().lower() in wanted_audio
                        for lang in tier.get("audio_languages") or []))
            # The switch order is what a naive "first tier" client presses:
            # free before gated, preferred audio first inside each class,
            # best band first inside that.
            merged["tiers"].sort(key=lambda t: (
                bool(t.get("gated")), not bool(t.get("preferred_audio")),
                tiers.band_rank(t["band"])))
            # `auto` is the tier the player should start at: the best
            # playable tier the caller's plan actually lets through, in
            # their preferred audio when one exists. Recomputed here, on
            # the raw links, because the projection below drops the
            # evidence keys `tiers.score` reads.
            playable = [t for t in merged["tiers"]
                        if t.get("playable") and not t.get("gated")]
            if playable:
                best = max(playable, key=lambda t: (
                    bool(t.get("preferred_audio")),
                    tiers.score(t["link"], t["band"]),
                    -tiers.band_rank(t["band"])))
                merged["auto"] = {"band": best["band"], "reason": "best",
                                  "stream_id": (best["link"] or {}).get("stream_id")}
            else:
                merged["auto"] = None
            for tier in merged["tiers"]:
                backups = tier.pop("backups", None) or []
                if tier["link"] is not None:
                    tier["link"] = redact.project(tier["link"], "ladder_link")
                # Only the runner-up *handles* travel. The player turns a handle
                # into our own /api/v1/stream URL exactly as it does for the
                # winner, so a backup needs nothing more to start — and a backup's
                # diagnostics are as private as the winner's.
                tier["backup_handles"] = [str(item["stream_id"]) for item in backups
                                          if item.get("stream_id")]
            groups.append({"season": season, "episode": episode, **merged})
    groups.sort(key=lambda group: tiers.scope_sort_key(group["season"],
                                                       group["episode"]))
    return groups


#: Plain-language words for the stream/download failures a player can hit.
#: The error code stays machine-readable; the message is what the app shows
#: instead of a raw HTTP status (audit #13/#14: never a bare code on screen).
_STREAM_ERROR_MESSAGES = {
    "premium_quality_requires_vip":
        "This quality needs VIP. A lower quality is included — try that instead.",
    "no_playable_source":
        "That copy didn't play. Try another quality.",
}


def _plain_stream_error(error: str) -> dict:
    return {"success": False, "error": error,
            "message": _STREAM_ERROR_MESSAGES.get(
                error, "That copy didn't play. Try another quality.")}


def _preresolve_is_warm(source_id: int) -> bool:
    """True when the resolved cache already holds a servable answer."""
    try:
        import resolved_cache
        with get_db() as conn:
            return resolved_cache.lookup_cache(conn, int(source_id),
                                               want="watch") is not None
    except Exception:      # noqa: BLE001 — a cache fault is "not warm", never an error
        return False


# Resolve coalescing (Appetize FAILED 1, 2026-11-12): one in-flight live
# resolve per (source, contract), shared by every caller that needs it.
#
# The failure it fixes: a detail open starts a daemon warm of the auto
# tier's link (`_resolve_and_bank`, 9.25 s measured for Salaar 720p). A Play
# press before it banks finds a cache MISS and starts a SECOND full resolve,
# and the player's 8 s watchdog fires before either finishes; the retry
# starts a THIRD resolve and the failover hop a FOURTH — ~30 s of parallel
# cold resolves, all abandoned, ending in NO_CANDIDATE_LEFT. The resolver
# has no internal lock, so nothing ever stopped the duplication. With
# coalescing the Play press joins the warm's resolve and 302s when it banks,
# inside the retry watchdog window.
#
# The leader runs the resolve; a waiter joins the in-flight one for up to
# `_RESOLVE_WAIT_SECONDS` and then uses the leader's answer. A waiter that
# times out, or whose leader failed, falls back to its own resolve — the old
# behaviour — so a stuck leader can never wedge a request. The key includes
# `v2` and `want` because the resolver's answer shape depends on both; a
# download must never inherit a watch-shaped answer or vice versa. The v2
# metadata resolve (`resolve_target` in api_v2.py) is deliberately NOT
# coalesced: it is a metadata read, not a playback path, and waiting up to
# 12 s on a play resolve would slow it. The wait bound sits under nginx's
# 15 s proxy read timeout so a joined resolve still answers in time.
_RESOLVE_IN_FLIGHT: dict = {}
_RESOLVE_IN_FLIGHT_LOCK = threading.Lock()
_RESOLVE_WAIT_SECONDS = 12.0


class _InFlightResolve:
    """One in-flight live resolve: the event the leader sets when done."""

    __slots__ = ("event", "result")

    def __init__(self):
        self.event = threading.Event()
        self.result = None


def _resolve_coalesced(source_id: int, *, v2: bool = False,
                       want: str = "watch") -> dict:
    """Resolve one link, joining an in-flight resolve for the same source.

    Returns the resolver's dict, a fresh copy per caller so nobody mutates a
    shared answer. A waiter that times out, or whose leader left no usable
    answer, resolves on its own, exactly as before this change.
    """
    import fast_fetch
    key = (int(source_id), bool(v2), str(want))
    with _RESOLVE_IN_FLIGHT_LOCK:
        inflight = _RESOLVE_IN_FLIGHT.get(key)
        if inflight is None:
            inflight = _InFlightResolve()
            _RESOLVE_IN_FLIGHT[key] = inflight
            leader = True
        else:
            leader = False
    if not leader:
        if inflight.event.wait(timeout=_RESOLVE_WAIT_SECONDS):
            result = inflight.result
            if isinstance(result, dict):
                return dict(result)
        return fast_fetch.resolve_live_source(int(source_id), v2=v2, want=want)
    try:
        result = fast_fetch.resolve_live_source(int(source_id), v2=v2, want=want)
        inflight.result = result if isinstance(result, dict) else {"success": False}
        return dict(inflight.result)
    finally:
        inflight.event.set()
        with _RESOLVE_IN_FLIGHT_LOCK:
            if _RESOLVE_IN_FLIGHT.get(key) is inflight:
                del _RESOLVE_IN_FLIGHT[key]


def _resolve_and_bank(source_id: int) -> None:
    """Resolve one link and bank it, for the background pre-resolve.

    Never raises: a warm-up that fails leaves the cache as it was, and the
    Play press pays the live resolve exactly as it would have without one.
    An endpoint-answered failure also writes its evidence (Player Fix v2
    §6.3): the warm is a probe, and a probe that proves a link dead must
    be visible to every path. Transport failures record nothing.
    """
    try:
        import resolved_cache
        res = _resolve_coalesced(int(source_id), want="watch")
        if res.get("success") and res.get("url") and not res.get("stale"):
            with get_db() as conn:
                resolved_cache.record_resolved_cache(conn, int(source_id), res)
        elif isinstance(res, dict):
            cause = res.get("fail_cause")
            if isinstance(cause, int) or cause == "not_media":
                import serve_verify
                reason = ("http_%d" % cause) if isinstance(cause, int) \
                    else "webview"
                with get_db() as conn:
                    serve_verify.record_probe_failure(
                        conn, int(source_id), reason,
                        http_status=cause if isinstance(cause, int) else 0)
    except Exception:      # noqa: BLE001 — see _preresolve_is_warm
        pass


def _start_preresolve(source_id: int):
    """Warm one link in a daemon thread; returns the thread for tests."""
    import threading
    thread = threading.Thread(target=_resolve_and_bank, args=(int(source_id),),
                              daemon=True, name="preresolve")
    thread.start()
    return thread


def _split_audio_param(value) -> tuple:
    """``?audio=Hindi,English`` -> ``("Hindi", "English")`` (empty -> ())."""
    if not value:
        return ()
    return tuple(part.strip() for part in str(value).split(",") if part.strip())


def _preresolve_for_detail(p_dict: dict) -> dict:
    """Warm every band's top candidate in parallel; report warm/warming.

    The detail screen opens long before the user presses Play: resolving
    the top link of EVERY band now means the press answers from the
    resolved cache (~0.02 s measured) instead of paying a 5–11 s live
    resolve while the player spins (audit #1). Warming only the auto
    tier left every other quality cold — the quality card's first press
    on any other band paid the full cold resolve — so every band's winner
    warms, each in its own daemon thread, kicked off the moment the
    detail request arrives (research fold-in §1: this warm IS the async
    re-verification of the title's bands). The `band` key stays for the
    auto tier, for callers that read it; `bands` names every band warmed.
    """
    bands: list = []
    warmed: list = []
    warming: list = []
    for group in p_dict.get("option_groups") or []:
        for tier in (group or {}).get("tiers") or []:
            link = (tier or {}).get("link") or {}
            stream_id = link.get("stream_id")
            if not stream_id:
                continue
            try:
                source_id = redact.parse_token(stream_id, signing_secret(),
                                               signed_only=True)
            except Exception:      # noqa: BLE001 — an unparseable handle is unavailable
                continue
            if not source_id:
                continue
            band = (tier or {}).get("band")
            bands.append(band)
            if _preresolve_is_warm(int(source_id)):
                warmed.append(band)
            else:
                _start_preresolve(int(source_id))
                warming.append(band)
    if not bands:
        return {"status": "unavailable"}
    auto = ((p_dict.get("option_groups") or [{}])[0].get("auto") or {})
    return {"status": "warm" if not warming else "warming",
            "band": auto.get("band"), "bands": bands,
            "warmed": warmed, "warming": warming}


def api_v1_rules() -> dict:
    """**Operator-only, loopback port.** Client-side bridge-unwrapping selectors.

    This map is the recipe for turning a hoster's share page into a file URL.
    While the public port served it, any app could copy the catalog *and* the
    unwrapping with two requests, so unwrapping moved server-side
    (`fast_fetch.resolve_live_source`, reached through `/api/v1/stream`): the
    client asks to play, the server works out what to play. Nothing here is
    deleted — an operator on this machine still needs the rules to diagnose a
    bridge that broke — but it is no longer a public document.
    """
    return {
        "version": "1.0",
        "name": "radd-stream-client-rules",
        "description": "Client-side extraction selectors for Android/Web direct unwrapping",
        "services": {
            "pixeldrain": {
                "pattern": r"https://pixeldrain\.com/u/([A-Za-z0-9_-]+)",
                "endpoint": "https://pixeldrain.com/api/file/{id}",
                "is_temporary": 0,
                "tier": 1
            },
            "vegadrive": {
                "pattern": r"https://(?:one\.)?vegadrive\.(?:me|app)/(?:s|d)/([A-Za-z0-9_-]+)",
                "endpoint": "https://one.vegadrive.me/d/{id}/skyd",
                "is_temporary": 0,
                "tier": 1
            },
            "vcloud": {
                "type": "double_base64_html",
                "regex": r"atob\(\s*atob\(\s*['\"]([^'\"]+)['\"]\s*\)\s*\)",
                "tier": 2
            },
            "hubcloud": {
                "type": "drive_page_gamerxyt",
                "regex": r'href=["\'](https?://gamerxyt\.com/hubcloud\.php\?[^"\']+)["\']',
                "tier": 2
            },
            "direct_cloud": {
                "pattern": r"https://(?:dl\.)?direct-cloud\.(?:top|org)/d/([A-Za-z0-9_-]+)",
                "action_endpoint": "https://storage.direct-cloud.org/action",
                "action_type": "DOWNLOAD_GENERATE",
                "tier": 2,
                "is_temporary": 1
            },
            "greenmotors": {
                "pattern": r"https://greenmotors\.[a-z]+/\?id=([A-Za-z0-9+/=_\-]+)",
                "type": "multi_layer_b64_rot13",
                "tier": 2,
                "is_temporary": 0
            }
        }
    }


_STATS_CACHE = {"time": 0.0, "data": None, "db": None}


def _meta_count(raw):
    """A stamped projection counter as an int, or `None` when the key is absent.

    `0` is a real answer here — a catalog nobody has knocked on has zero live links —
    so a missing key must not collapse into it.
    """
    if raw is None or str(raw).strip() == "":
        return None
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return None


def _meta_by_state(raw):
    """The stamped adult-excluded link breakdown, or `None` when there is none.

    A stored `{}` is `None` here: a projection that wrote no `cat_links` rows at all
    is indistinguishable from a stamp that predates the key, and the second case must
    fall back to counting rather than publish a catalog with no links in it."""
    if raw is None or str(raw).strip() == "":
        return None
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(parsed, dict) or not parsed:
        return None
    return {str(state): int(count or 0) for state, count in parsed.items()}


#: `download_sources.status` -> projection vocabulary, as SQL.
#:
#: A scraper writes 'active' into every row at ingest and only `link_state.propagate()`
#: retires that claim, so `status = 'active'` alone says nothing about whether anybody
#: knocked. This is `_link_state_of()`'s rule (`catalog_v2.py`) told to SQLite: an
#: absent or unprobed 'active' is 'unchecked', and only measured evidence — a
#: `last_checked_at` or a real `http_status` — makes one 'active'.
_LEDGER_STATE_SQL = """
    CASE
      WHEN d.status IS NULL OR d.status = '' OR d.status = 'unverified' THEN 'unchecked'
      WHEN d.status = 'active' THEN
        CASE WHEN d.last_checked_at IS NULL
                  AND (d.http_status IS NULL OR d.http_status = 0)
             THEN 'unchecked' ELSE 'active' END
      WHEN d.status IN ('dead', 'expired', 'unknown') THEN d.status
      ELSE 'unchecked'
    END
"""


def _ledger_link_breakdown(conn):
    """(by_state, resumable, temporary) for the displayable ledger, counted live.

    The fallback for a catalog with no safe stamp on it. Uses `_LEDGER_STATE_SQL`, so
    a scraper's blanket 'active' lands in 'unchecked' here exactly as it does in the
    projection, and the adult clause, so no number below can be reached by an 18+ row.
    """
    by_state, resumable_c, temp_c = {}, 0, 0
    for row in conn.execute(
            f"SELECT {_LEDGER_STATE_SQL} AS state,"
            " COUNT(*) AS n,"
            " SUM(CASE WHEN d.is_resumable = 1 THEN 1 ELSE 0 END) AS resumable,"
            " SUM(CASE WHEN d.is_temporary = 1 THEN 1 ELSE 0 END) AS temporary"
            " FROM download_sources d"
            " JOIN releases r ON r.id = d.release_id"
            " JOIN posts p ON p.id = r.post_id"
            f" WHERE {redact.adult_clause('p')}"
            " GROUP BY state").fetchall():
        name = str(row["state"] or "unchecked")
        count = int(row["n"] or 0)
        by_state[name] = by_state.get(name, 0) + count
        resumable_c += int(row["resumable"] or 0)
        temp_c += int(row["temporary"] or 0)
    return dict(sorted(by_state.items())), resumable_c, temp_c


def _counted_stats(conn):
    """The whole stats body, counted live from the ledger with the adult rule applied.

    Used when the projection carries no safe stamp yet (a catalog merged before these
    counters existed, or one that was never projected at all).
    """
    try:
        posts_c = conn.execute(
            "SELECT COUNT(*) FROM cat_works WHERE " + redact.adult_clause("cat_works")
        ).fetchone()[0]
    except Exception:
        posts_c = conn.execute(
            "SELECT COUNT(*) FROM posts WHERE " + redact.adult_clause("posts")
        ).fetchone()[0]
    rels_c = conn.execute(
        f"SELECT COUNT(*) FROM releases r JOIN posts p ON p.id = r.post_id"
        f" WHERE {redact.adult_clause('p')}"
    ).fetchone()[0]
    by_state, resumable_c, temp_c = _ledger_link_breakdown(conn)
    return {
        "posts": posts_c,
        "releases": rels_c,
        "sources": sum(by_state.values()),
        "active_sources": by_state.get("active", 0),
        "resumable_sources": resumable_c,
        "temporary_sources": temp_c,
        "sources_by_state": by_state,
    }


def _get_cached_stats(conn):
    import time
    now = time.time()
    # Keyed by DB_PATH, the way `_ensure_schema` keys its readiness flag: `get_db()`
    # hands every request a fresh connection, so a `conn` identity would never match
    # and the cache would answer the previous database for two minutes after a switch.
    if (_STATS_CACHE["data"] is not None and _STATS_CACHE["db"] == DB_PATH
            and (now - _STATS_CACHE["time"]) < 120.0):
        return _STATS_CACHE["data"]

    meta = {}
    try:
        meta = dict(conn.execute("SELECT key, value FROM cat_projection_meta").fetchall())
    except Exception:
        pass

    # The numbers this endpoint publishes, in the adult-excluded form the projection
    # stamped for them. All or nothing: mixing a stamp with a live count would publish
    # two snapshots taken at different times, so a partial stamp falls back to counting.
    safe_keys = ("works_safe", "releases_safe", "links_resumable_safe",
                 "links_temporary_safe")
    safe = {name: _meta_count(meta.get(name)) for name in safe_keys}
    by_state = _meta_by_state(meta.get("links_by_state_safe"))

    if None in safe.values() or by_state is None:
        res = _counted_stats(conn)
    else:
        # `sources` and `active_sources` are read out of the breakdown rather than
        # taken beside the `links_safe`/`links_active_safe` stamps: one is derived from
        # the other here, so the response can never publish a total and a distribution
        # of it that disagree — the mistake this whole function started making was
        # printing `active_sources` equal to `sources`.
        res = {
            "posts": safe["works_safe"],
            "releases": safe["releases_safe"],
            "sources": sum(by_state.values()),
            "active_sources": by_state.get("active", 0),
            "resumable_sources": safe["links_resumable_safe"],
            "temporary_sources": safe["links_temporary_safe"],
            "sources_by_state": by_state,
        }
    _STATS_CACHE["time"] = now
    _STATS_CACHE["data"] = res
    _STATS_CACHE["db"] = DB_PATH
    return res


def bounded_int(query_params, name, default, lo, hi):
    """A public query parameter that is meant to be a number.

    Bare `int()` on caller text was raising out of the handler for `?page=abc`
    and the edge answered 502 — an unauthenticated caller could make that happen
    on every request it liked, and each one wrote a traceback. The fallback is
    the documented default, same as `/api/v1/search/by-media` already did.
    """
    try:
        value = int(str(query_params.get(name, [default])[0]).strip())
    except (TypeError, ValueError):
        return default
    return min(hi, max(lo, value))


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class DashboardHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def send_bytes(self, data: bytes, content_type: str = "text/html; charset=utf-8", status: int = 200, extra_headers: list[tuple[str, str]] | None = None):
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Connection", "close")
            headers = list(extra_headers or [])
            headers.extend(getattr(self, "rate_headers", []))
            cookie = getattr(self, "operator_cookie", "")
            if cookie:
                headers.append(("Set-Cookie", cookie))
            if headers:
                for k, v in headers:
                    self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)
        except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
            pass

    def send_json(self, data: any, status: int = 200,
                  extra_headers: list[tuple[str, str]] | None = None):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        headers = cors_headers_for(self.headers.get("Origin", ""))
        if extra_headers:
            headers.extend(extra_headers)
        self.send_bytes(body, content_type="application/json; charset=utf-8",
                        status=status, extra_headers=headers)

    def send_triple(self, answered: tuple, extra_headers: list[tuple[str, str]] | None = None) -> None:
        """One `(status, content_type, body)` answer from `admin_panel` or
        `accounts_api` — the tuple contract both use so each stays testable as a
        function call and this stays the only thing that writes a socket.
        `send_bytes` adds the `RateLimit-*` triple and closes the connection, so
        the headers a bucket already bought are not thrown away at the last step.

        `extra_headers` exists for the sign-in flow, which has to emit `Location`
        and `Set-Cookie` on a 303: the triple carries a status, a type and a body,
        and a redirect is none of those. Nothing else about the contract changes.
        """
        status, content_type, body = answered
        self.send_bytes(body, content_type=content_type, status=status,
                        extra_headers=extra_headers)

    def _bucket_for(self, path: str, method: str = "GET") -> str:
        if path in admin_panel.LOGIN_PATHS or path in admin_panel.LOGOUT_PATHS:
            # Named here so a sign-in route can never inherit `browse` by accident
            # of a fall-through if anyone ever mounts it on the public port. On the
            # operator port it is charged directly, in `_operator_login`, because
            # this gate does not run there.
            return "auth"
        if accounts_api.is_account(path):
            # Account writes are small and boring; the reason for a budget of their
            # own is the sync key. A caller may hammer `Authorization` guesses all
            # afternoon, and `accounts.LIMITER` charges failures per key — an
            # unthrottled port would just let it spend other people's budgets.
            return "account"
        if api_v2.is_v2(path):
            # The v2 budget is the same token bucket, under the route map in
            # `api_v2.ROUTE_BUCKETS`; there is no second limiter.
            return api_v2.bucket_for(path, method)
        if path in ("/api/v1/stream", "/api/v1/download", "/api/v1/art", "/api/m3u"):
            return "play"
        if path == "/api/v1/stats":
            return "reports"
        return "browse"

    #: Headers that only the public reverse proxy puts on a request. Their presence
    #: means "this came in through port 80", which for the operator port is exactly
    #: the thing that must never be true — see `_through_public_proxy`.
    _PROXY_MARKERS = ("X-Forwarded-For", "X-Real-IP", "X-Forwarded-Proto")

    def _through_public_proxy(self) -> bool:
        """True when this request carries a reverse-proxy marker.

        Measured 2026-10-31 and the reason this method exists: the enabled nginx
        site has `location /operator/ { proxy_pass http://127.0.0.1:8081/; }`, so the
        operator port — the one whose entire access model is "a process on this
        machine" — was reachable from the public internet, prefix-stripped, and
        `admin_panel._gate`'s loopback rule passed for every visitor because nginx
        connects *from* 127.0.0.1. Fixing that properly is an owner action on a file
        that is not in this repo. This is the code-side wall: a direct loopback
        client sends no `X-Forwarded-For`, the public proxy always does, and so a
        marker here means the edge let something in that the edge was never meant to
        serve.

        It is deliberately a *refusal*, not a trust decision: an attacker can omit
        the headers and gain nothing they did not already have, while a local process
        that adds them only locks itself out. `RADD_TRUST_EDGE_PROXY=1` opts out, for
        an operator who has put a real authentication in front of the proxy and means
        it. A local attacker who can already write to the loopback socket can already
        do anything the port allows — this closes the *remote* path, which is the one
        that was open.
        """
        if os.environ.get("RADD_TRUST_EDGE_PROXY", "").strip() == "1":
            return False
        return any(self.headers.get(name) for name in self._PROXY_MARKERS)

    def _accepts_html(self) -> bool:
        """Whether the caller asked for HTML, which decides the shape of a refusal.
        Deliberately not used for anything but that: `Accept` is caller-controlled,
        so it may choose between two refusals and never between a refusal and data.
        """
        return "text/html" in str(self.headers.get("Accept", "") or "")

    def _operator_login(self, path: str, method: str) -> bool:
        """Serve sign-in and sign-out ahead of the gate. True when this handled it.

        These are the only operator-port paths that answer before a credential
        exists, and both re-check the peer themselves (`admin_panel.authenticate`
        refuses a non-loopback peer before comparing anything), so opening them is
        not opening the port. Everything else on this socket still faces the gate
        first.

        `method` decides which of three answers this is, and that is not decoration:
        a `GET` on the login path is a person arriving at the door, so it renders the
        form at 200 and spends no sign-in budget, while a `POST` is an *attempt*,
        charged to the `auth` bucket before a byte of the body is read. A `GET` on the
        logout path is refused with 405 rather than honoured, because the only thing
        that reliably follows a `GET` nobody typed is a prefetcher, a link scanner or
        an image loader — and a logout that a robot can trigger is a denial of service
        against the one person who is allowed to use this panel.

        Reading the body is the mount's job and never the module's, so the form is
        parsed here — capped at the same ceiling every other admin body uses, since
        an unbounded `Content-Length` on a page that answers without a credential is
        a free memory grab.
        """
        if path not in admin_panel.LOGIN_PATHS and path not in admin_panel.LOGOUT_PATHS:
            return False
        if self._through_public_proxy():
            # Not even a form: from the public edge, this surface does not exist.
            self.send_json({"success": False, "error": "not_found"}, status=404)
            return True
        peer = str(self.client_address[0] or "")
        if method != "POST":
            if path in admin_panel.LOGOUT_PATHS:
                self.send_json({"success": False, "error": "method_not_allowed"},
                               status=405,
                               extra_headers=[("Allow", "POST"),
                                              ("Cache-Control", "no-store")])
                return True
            answered, headers = admin_panel.login_page(path, peer_address=peer)
            self.send_triple(answered, extra_headers=headers)
            return True
        if path in admin_panel.LOGIN_PATHS:
            # One budget per address for sign-in attempts, spent before a byte of
            # the body is read and before `authenticate` runs, so a refused attempt
            # costs this box nothing but a counter tick — and so the memory-hard
            # password derive in `admin_panel.verify_password` cannot be turned
            # into a CPU buy by a caller who never authenticates.
            #
            # The key is the SOCKET peer, not `redact.client_ip(self)`: on this port
            # `X-Real-IP` is a caller-typed string unless the proxy refusal above
            # fired, and a limiter an attacker can rename is decoration. Loopback
            # means exactly one bucket for the box, which is the point — the
            # per-username lockout in `admin_panel` is what separates two people
            # sharing it. Sign-out is deliberately not charged: locking out a
            # logout buys an attacker nothing and punishes an operator who is
            # already authenticated.
            verdict = redact.limiter.check("auth", peer)
            self.rate_headers = redact.limiter.headers(verdict)
            if not verdict["allowed"]:
                self.send_triple(
                    admin_panel._problem(
                        "rate_limited", path,
                        "Too many sign-in attempts from this address.", stable=True),
                    extra_headers=[("Retry-After", str(verdict["retry_after"])),
                                   ("Cache-Control", "no-store")])
                return True
        body = None
        if path in admin_panel.LOGIN_PATHS:
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except (TypeError, ValueError):
                length = 0
            length = max(0, min(length, api_v2.MAX_BODY_BYTES))
            body = admin_panel.parse_form_body(self.rfile.read(length)) if length else {}
        self.operator_cookie = ""
        if path in admin_panel.LOGOUT_PATHS:
            answered, headers = admin_panel.logout_response(path, peer_address=peer)
        else:
            answered, headers = admin_panel.login_submit(
                path, body, peer_address=peer, accepts_html=self._accepts_html())
        self.send_triple(answered, extra_headers=headers)
        return True

    def _operator_gate(self) -> bool:
        """The credential every route on the operator port now requires.

        Called first, before any SQL and before the panel is consulted, because
        this is the whole point: `/`, `/client`, `/api/v1/stats` and
        `/api/v1/rules` are not `/admin` and were never routed through
        `admin_panel._gate`, so on this port they answered whoever reached the
        socket. Loopback is the boundary only while nothing is listening on the
        other side of it — and `_through_public_proxy` is what keeps that sentence
        true after someone adds a proxy. A loopback peer that is not the proxy is a
        process on this box; this box runs a web IDE as root, so the credential is
        checked regardless.

        There is no `?token=` any more, in this method or anywhere behind it: a
        credential that travels in a URL is recorded in browser history, in the
        `Referer`, and in nginx's access log, all of which outlive the session it was
        meant to open. Present `Authorization: Bearer` or sign in.

        Returns True when the caller may proceed. A proven bearer credential also
        mints the short-lived session cookie the dashboard needs to fetch
        `/api/data`; a session alone is accepted, and refusal is the same
        byte-for-byte body whether the caller presented nothing or nonsense.
        """
        if self._through_public_proxy():
            # 404, not 403: the same sentence the login door tells. A 403 here would
            # confirm to a scanner that an operator surface answers behind this edge
            # and only needs the right request, which is the one thing worth hiding.
            self.send_triple(admin_panel._problem(
                "not_found", "/operator", "No such route.", stable=True))
            return False
        refusal, session_cookie = admin_panel.gate_operator_port(
            self.client_address[0],
            authorization=self.headers.get("Authorization", ""),
            cookie=self.headers.get("Cookie", ""),
            accepts_html=self._accepts_html())
        self.operator_cookie = session_cookie or ""
        if refusal is not None:
            self.send_triple(refusal)
            return False
        return True

    def _count_playback(self, path: str) -> None:
        """One server-observed play, into the operator's usage counters.

        Counted on the public port only: an operator's own smoke test through
        the panel is not a user pressing play, and letting it inflate the
        playback totals would make the dashboard's headline number a lie about
        traffic that no human generated. A write is one UPSERT on a rate-limited
        route, and `usage_stats` swallows every failure — analytics never gets
        to be the reason playback was slow.
        """
        if path in PLAYBACK_ROUTES and not getattr(self.server, "operator", False):
            usage_stats.record_event(
                accounts_api.state_db(), metric="playback_start", count=1,
                dims=usage_stats.attributes_from_headers(self.headers))

    def _public_gate(self, path: str, method: str = "GET") -> bool:
        """The edge every public request passes: no operator route, one token
        bucket, the `RateLimit-*` triple on whatever we answer (§16.5).

        Returns True when the caller may proceed. The operator flag lives on the
        server instance, so this gate is the loopback port's absence, never a
        header a client can set.
        """
        if path in OPERATOR_ONLY_ROUTES or path.startswith(OPERATOR_ONLY_PREFIXES):
            self.send_json({"success": False, "error": "not_found"}, status=404)
            return False
        # The play bucket is the operator's knob: refresh its limit from
        # the panel (cached for a minute) before charging this request, so
        # a tuning change takes effect without a restart and an unwired
        # panel keeps the shipped 30.
        redact.limiter.limits["play"] = (_play_limit_per_min(), 60.0)
        verdict = redact.limiter.check(self._bucket_for(path, method),
                                       redact.client_ip(self))
        self.rate_headers = redact.limiter.headers(verdict)
        if not verdict["allowed"]:
            if api_v2.is_v2(path):
                api_v2.problem(self, code="rate_limited", rid=api_v2.request_id(),
                               instance=path,
                               detail="This client is over its request budget.",
                               headers=[("Retry-After", str(verdict["retry_after"]))])
            else:
                self.send_json({"success": False, "error": "rate_limited"}, status=429,
                               extra_headers=[("Retry-After",
                                                str(verdict["retry_after"]))])
        return verdict["allowed"]

    def _merchant_relay(self, path: str) -> bool:
        """`POST /api/v2/payment/sms-webhook` — the bank SMS the merchant's relay
        forwards here, answered by `payments.sms_webhook`.

        Returns True when this route answered. It is mounted on the public POST
        chain rather than in `admin_panel`, because the operator surface is loopback
        plus `RADD_ADMIN_TOKEN` and a merchant's callback can do neither: it cannot
        reach a socket on this box's loopback, and it has no business holding an
        operator's token. The credential is the separate `X-Merchant-Secret`, checked
        before a byte of the body is read — an unauthorized caller spends 401 and no
        ledger query, and gets the identical 401 whether its body was empty, huge or
        nonsense.

        The callback pays into the ordinary browse budget (`_bucket_for`'s fall
        through): a relay forwards a handful of SMS a day, and because
        `payments.sms_webhook` is replay-safe, a 429 costs the relay a retry rather
        than a payment.

        NOTE — this path is under `/api/v2/` but NOT under `/api/v2/account`, and
        nginx allow-lists the account prefix while `^~ /api/` 403s the rest of `/api/`
        (`ORACLE_DEPLOYMENT.md`, and the measured edge in `AGENTS.md`). That 403 is
        the control, and it stays (`docs/RADD_RELAY_AND_AUTH_ARCHITECTURE.md` R1-R2):
        on a plain-HTTP host a static merchant secret that crossed the public edge
        would be sniffable by anyone on the path, and whoever held it could approve
        their own VIP indefinitely. The sanctioned transport is the operator phone's
        OUTBOUND SSH tunnel — `autossh -M 0 -N -L 127.0.0.1:8099:127.0.0.1:8080
        ubuntu@<host>`, the relay POSTing to `http://127.0.0.1:8099` + this path —
        which lands on exactly this handler over loopback, needs no edge change, and
        buys encryption plus device authentication for $0. So this route answers on
        the loopback ports and nowhere publicly, by design, and nothing here asks
        the owner for a `location` line.
        """
        if not payments.verify_merchant_header(self.headers):
            api_v2.problem(self, code="unauthorised", rid=api_v2.request_id(),
                           instance=path,
                           detail="The callback must carry the merchant secret.")
            return True
        payload, code = api_v2.read_body(self)
        if payload is None:
            api_v2.problem(self, code=code or "invalid_params",
                           rid=api_v2.request_id(), instance=path)
            return True
        try:
            answer = payments.sms_webhook(
                accounts_api.state_db(), gateway=payload.get("gateway"),
                tid=payload.get("tid"), amount=payload.get("amount"))
        except payments.PaymentError as error:
            api_v2.problem(self, code=getattr(error, "code", "invalid_params"),
                           rid=api_v2.request_id(), instance=path,
                           detail=str(getattr(error, "detail", "") or ""))
            return True
        self.send_json(answer)
        return True

    def _serve_art(self, query_params: dict, full: bool = False) -> None:
        """302 to a work's own artwork, addressed by our handle.

        Posters are the one piece of upstream content a user sees directly, and
        a scraped site's own image URL prints that site's domain in the UI's
        image inspector — so art is addressed the same way video is: our host,
        our handle, a redirect, zero bytes through this box."""
        post_id = redact.parse_token(query_params.get("id", [""])[0], signing_secret(),
                                     signed_only=not full)
        kind = (query_params.get("k", ["poster"])[0] or "poster").lower()
        table = (query_params.get("t", ["posts"])[0] or "posts").lower()
        if table not in redact.ART_TABLES:
            table = "posts"
        try:
            index = max(0, int(query_params.get("n", ["0"])[0]))
        except ValueError:
            index = 0
        if not post_id or kind not in ("poster", "backdrop"):
            self.send_json({"error": "Invalid art reference"}, status=400)
            return
        if redact.art_is_adult(int(post_id), DB_PATH, table=table):
            self.send_json({"success": False, "error": "not_found"}, status=404)
            return
        target = redact.art_url_for(int(post_id), kind, index, DB_PATH, table=table)
        if not target:
            self.send_bytes(b"Not Found", content_type="text/plain", status=404)
            return
        self.send_response(302)
        self.send_header("Location", target)
        for name, value in cors_headers_for(self.headers.get("Origin", "")):
            self.send_header(name, value)
        self.send_header("Cache-Control", "public, max-age=86400")
        self.send_header("Connection", "close")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query_params = urllib.parse.parse_qs(parsed.query)
        # Whether this server may speak provenance at all. Set on the *instance*
        # (see start_server), so it cannot be negotiated by a request header or a
        # query parameter — the whole point of a separate loopback port.
        full = bool(getattr(self.server, "operator", False))
        if full:
            # Sign-in is the one thing on this port that answers before a credential
            # exists, so it goes ahead of the gate; the gate then covers every other
            # path, including every read that used to be free on loopback.
            if self._operator_login(path, "GET"):
                return
            if not self._operator_gate():
                return
        base_url = "" if full else _public_base(self)
        if not full and not self._public_gate(path, "GET"):
            return
        self._count_playback(path)

        if path.startswith(OPERATOR_ONLY_PREFIXES):
            # Reached only on the loopback instance: `_public_gate` 404s this
            # prefix on the public port, so a caller there cannot even learn the
            # panel exists. The module re-checks the peer and the bearer token.
            if not full:
                self.send_json({"success": False, "error": "not_found"}, status=404)
                return
            answered = admin_panel.route_get(
                path, query_params, db_path=DB_PATH,
                peer_address=self.client_address[0],
                token_header=self.headers.get("Authorization", ""),
                state_db_path=accounts_api.state_db(),
                cookie_header=self.headers.get("Cookie", ""),
                accepts_html=self._accepts_html())
            if answered is not None:
                self.send_triple(answered)
                return

        if accounts_api.is_account(path):
            # Optional sync accounts ride the public port — a phone has no other
            # way to reach them — but they never see provenance: `accounts_api`
            # mints every work identifier through `signing_secret()`, the same
            # handle machinery `/play` uses, and refuses anything it did not mint.
            _ensure_schema()
            answered = accounts_api.route_get(
                path, query_params, db_path=accounts_api.state_db(), catalog_path=DB_PATH,
                secret=signing_secret(), headers=self.headers)
            if answered is not None:
                self.send_triple(answered)
                return

        if api_v2.is_v2(path):
            # The whole v2 surface (§12) is mounted here and only here: every
            # payload comes out of `catalog_api`, whose `@public_edge` decorator
            # runs `redact.scrub`, so a field added to a view later is denied
            # rather than published.
            _ensure_schema()
            if api_v2.route_get(self, path, query_params, db_path=DB_PATH,
                                operator=full, base_url=_public_base(self),
                                secret=signing_secret()):
                return

        if path == "/api/data":
            search_q = query_params.get("q", [""])[0]
            # `stats=full` is the operator's explicit "count it live, I know what
            # it costs". Anything else — including a typo — is the stamped answer,
            # because the expensive branch must be chosen, never fallen into.
            mode = query_params.get("stats", ["stamp"])[0].strip().lower()
            if mode not in _LEDGER_STATS_MODES:
                mode = "stamp"
            data = fetch_database_payload(
                search_q, full=full, base_url=base_url,
                # The raw parameter, deliberately: the clamp lives in the payload
                # builder so it can report `page.clamped`. Clamping here would make
                # that flag structurally unable to ever be true.
                limit=query_params.get("limit", [""])[0],
                page=bounded_int(query_params, "page", 1, 1, 100000),
                stats=mode)
            self.send_json(data)

        elif path == "/api/sitemap":
            if not full:
                self.send_json({"success": False, "error": "not_found"}, status=404)
                return
            search_q = query_params.get("q", [""])[0]
            site = query_params.get("site", [""])[0]
            # `bounded_int`, not a bare `int()`: the old spelling let `?limit=abc`
            # raise out of the handler, and an unclamped number let `?limit=99999999`
            # read the whole sitemap table on a one-vCPU box. The dashboard consumes
            # a bare list here, so the bound is applied and the shape is untouched.
            limit = bounded_int(query_params, "limit", 50, 1, _SITEMAP_ROW_CEILING)
            rows = search_sitemap_api(search_q, site=site, limit=limit)
            self.send_json(rows)

        elif path == "/api/fetch":
            if not full:
                # Scraping an arbitrary caller-supplied URL is an operator tool,
                # and an open one on the public port is an SSRF.
                self.send_json({"success": False, "error": "not_found"}, status=404)
                return
            target_url = query_params.get("url", [""])[0]
            if not target_url:
                self.send_json({"error": "Missing url"}, status=400)
                return

            try:
                import fast_fetch
                data = fast_fetch.extract_post_data(target_url, verbose=False)
                if data:
                    post_id = fast_fetch.save_scraped_data(data)
                    resp_payload = {"success": True, "post_id": post_id, "clean_title": data["clean_title"]}
                else:
                    resp_payload = {"success": False, "error": "Failed to parse post"}
            except Exception as ex:
                resp_payload = {"success": False, "error": str(ex)}

            self.send_json(resp_payload)

        elif path == "/api/m3u":
            # `?id=abc` used to raise ValueError straight out of do_GET, which
            # drops the connection with no response at all — the same 502 class
            # `bounded_int` exists to stop on `?page=abc`. Answer like the detail
            # route's invalid id: a 400 the caller can read.
            try:
                post_id = int(query_params.get("id", [0])[0])
            except (TypeError, ValueError):
                self.send_json({"error": "Invalid post ID"}, status=400)
                return
            playlist_content = generate_m3u_playlist(post_id, full=full, base_url=base_url)
            body = playlist_content.encode("utf-8")
            self.send_bytes(
                body,
                content_type="audio/x-mpegurl; charset=utf-8",
                extra_headers=[("Content-Disposition", f'attachment; filename="playlist_{post_id}.m3u"')]
            )

        elif path == "/api/health-check":
            # `keep_blank_values` so `?id=` is visible as an empty id rather than
            # silently becoming "no id" — which on this route means "sweep every
            # post", the most expensive request the panel can make. A blank value is
            # the caller's error, exactly like `abc`; it is not an invitation.
            query_params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
            # `/api/m3u` and `/api/v1/posts/{id}` all answer a malformed id with a
            # 400 the caller can read. A bare `int()` here raised out of `do_GET`
            # instead, and a handler that raises mid-request drops the socket with no
            # status and no body — which is indistinguishable, to the operator, from
            # the server having died. Same rule as the detail route: `?id=abc` is the
            # caller's error, so it is answered as one.
            post_id = None
            if query_params.get("id"):
                try:
                    post_id = int(query_params["id"][0])
                except (TypeError, ValueError):
                    self.send_json({"error": "Invalid post ID"}, status=400)
                    return
            try:
                import fast_fetch
                results = fast_fetch.run_health_check(post_id=post_id, verbose=False)
                resp_payload = {"success": True, "count": len(results)}
            except Exception as ex:
                resp_payload = {"success": False, "error": str(ex)}

            self.send_json(resp_payload)

        elif path == "/api/heal":
            # `keep_blank_values` for the same reason as `/api/health-check`: with the
            # default, `?id=` disappears and the route heals post 0, answering
            # `{"success": true, "error": "Post not found"}` — a 200 that contradicts
            # itself. A blank id is the caller's error and is answered as one.
            query_params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
            # The third member of the same defect class as `/api/m3u` and
            # `/api/health-check`: an unguarded `int()` on a query value raised out of
            # `do_GET` and dropped the connection. It is also the only one of the three
            # that *writes* — `heal_post_links` re-resolves links and updates rows — so
            # a malformed id must be refused before any of that begins, not midway.
            try:
                post_id = int(query_params.get("id", [0])[0])
            except (TypeError, ValueError):
                self.send_json({"error": "Invalid post ID"}, status=400)
                return
            try:
                import fast_fetch
                res = fast_fetch.heal_post_links(post_id, verbose=False)
                if "error" in res:
                    # A missing post is the caller's error, not a success:
                    # `heal_post_links` answers `{"healed": 0, "error": ...}`
                    # for it, and wrapping that in `success: True` was a 200
                    # that contradicted itself.
                    self.send_json({"success": False, "error": res["error"]},
                                   status=404)
                    return
                resp_payload = {"success": True, **res}
            except Exception as ex:
                resp_payload = {"success": False, "error": str(ex)}
            self.send_json(resp_payload)

        elif path == "/api/v1/posts":
            q = query_params.get("q", [""])[0]
            ctype = query_params.get("type", [""])[0]
            page = bounded_int(query_params, "page", 1, 1, 1_000_000)
            limit = bounded_int(query_params, "limit", 20, 1, 100)
            if (page - 1) * limit > POSTS_MAX_OFFSET:
                # The offset window is the exposure; the two numbers above are not.
                self.send_json({"success": False, "error": "page_beyond_range",
                                "max_offset": POSTS_MAX_OFFSET}, status=400)
                return
            try:
                data = api_v1_get_posts(
                    query=q, content_type=ctype, page=page, limit=limit,
                    full=full, base_url=base_url,
                    industry=query_params.get("industry", [""])[0],
                    genre=query_params.get("genre", [""])[0],
                    language=query_params.get("language", [""])[0],
                    quality=query_params.get("quality", [""])[0],
                    sort=query_params.get("sort", [""])[0],
                    free_only=query_params.get("free_only", [""])[0] == "1",
                    work_ref=query_params.get("work_ref", [""])[0],
                    region=query_params.get("region", [""])[0],
                )
            except sqlite3.OperationalError as exc:
                # The query ran past the 10 s search deadline: the progress
                # handler aborted it, which surfaces as "interrupted" (a
                # raise inside the callback is swallowed by sqlite3). Any
                # other OperationalError is not the deadline: re-raise it.
                if str(exc) != "interrupted":
                    raise
                self.send_json({"success": False, "error": "search_timeout"},
                               status=503)
                return
            self.send_json(data)

        elif path == "/api/v1/works":
            # One work per movie/series (see api_v1_get_works): the same
            # params as /api/v1/posts, the same page window, the same
            # 503 on a search that runs past the deadline.
            q = query_params.get("q", [""])[0]
            ctype = query_params.get("type", [""])[0]
            page = bounded_int(query_params, "page", 1, 1, 1_000_000)
            limit = bounded_int(query_params, "limit", 20, 1, 100)
            if (page - 1) * limit > POSTS_MAX_OFFSET:
                self.send_json({"success": False, "error": "page_beyond_range",
                                "max_offset": POSTS_MAX_OFFSET}, status=400)
                return
            try:
                data = api_v1_get_works(
                    query=q, content_type=ctype, page=page, limit=limit,
                    full=full, base_url=base_url,
                    industry=query_params.get("industry", [""])[0],
                    genre=query_params.get("genre", [""])[0],
                    language=query_params.get("language", [""])[0],
                    quality=query_params.get("quality", [""])[0],
                    sort=query_params.get("sort", [""])[0],
                    free_only=query_params.get("free_only", [""])[0] == "1",
                    work_ref=query_params.get("work_ref", [""])[0],
                    region=query_params.get("region", [""])[0],
                )
            except sqlite3.OperationalError as exc:
                if str(exc) != "interrupted":
                    raise
                self.send_json({"success": False, "error": "search_timeout"},
                               status=503)
                return
            self.send_json(data)

        elif path.startswith("/api/v1/works/"):
            parts = path.strip("/").split("/")
            if len(parts) == 4 and parts[3].isdigit():
                detail = api_v1_get_work_detail(
                    int(parts[3]), full=full, base_url=base_url,
                    ladder=query_params.get("ladder", ["1"])[0] not in ("0", "false"),
                    # Player Fix v2: serve only verified bands (cached
                    # verdict first, bounded live probe when never-checked).
                    verify=True)
                if detail:
                    self.send_json({"success": True, "data": detail})
                else:
                    # Identical to a row that never existed: an adult work
                    # must not be distinguishable from an absent one.
                    self.send_json({"success": False, "error": "Work not found"}, status=404)
            else:
                self.send_json({"error": "Invalid work ID"}, status=400)

        elif path == "/api/v1/trending":
            # The "Most Sources" rail as its own route (see api_v1_get_trending).
            page = bounded_int(query_params, "page", 1, 1, 1_000_000)
            limit = bounded_int(query_params, "limit", 20, 1, 100)
            if (page - 1) * limit > POSTS_MAX_OFFSET:
                self.send_json({"success": False, "error": "page_beyond_range",
                                "max_offset": POSTS_MAX_OFFSET}, status=400)
                return
            try:
                data = api_v1_get_trending(
                    page=page, limit=limit,
                    content_type=query_params.get("type", [""])[0],
                    base_url=base_url)
            except sqlite3.OperationalError as exc:
                if str(exc) != "interrupted":
                    raise
                self.send_json({"success": False, "error": "search_timeout"},
                               status=503)
                return
            self.send_json(data)

        elif path == "/api/v1/related":
            # "Because you watch" — work_id is a required v1 post id.
            raw_work_id = query_params.get("work_id", [""])[0].strip()
            if not raw_work_id.isdigit():
                self.send_json({"success": False, "error": "invalid work_id"},
                               status=400)
                return
            page = bounded_int(query_params, "page", 1, 1, 1_000_000)
            limit = bounded_int(query_params, "limit", 20, 1, 100)
            if (page - 1) * limit > POSTS_MAX_OFFSET:
                self.send_json({"success": False, "error": "page_beyond_range",
                                "max_offset": POSTS_MAX_OFFSET}, status=400)
                return
            try:
                data = api_v1_get_related(work_id=int(raw_work_id), page=page,
                                          limit=limit, base_url=base_url)
            except sqlite3.OperationalError as exc:
                if str(exc) != "interrupted":
                    raise
                self.send_json({"success": False, "error": "search_timeout"},
                               status=503)
                return
            self.send_json(data)

        elif path == "/api/v1/facets":
            # The browse jump-off chips (see api_v1_get_facets). No
            # parameters: the groups are the whole catalog's facets.
            try:
                data = api_v1_get_facets()
            except sqlite3.OperationalError as exc:
                if str(exc) != "interrupted":
                    raise
                self.send_json({"success": False, "error": "search_timeout"},
                               status=503)
                return
            self.send_json(data)

        elif path == "/api/v1/search/by-media":
            def number(name):
                raw = query_params.get(name, [""])[0].strip()
                return raw or None
            try:
                limit = int(query_params.get("limit", [10])[0])
            except ValueError:
                limit = 10
            data = api_v1_search_by_media(
                query=query_params.get("q", [""])[0],
                duration_s=number("duration_s"),
                resolution=number("resolution"),
                audio_language=query_params.get("language", [""])[0],
                limit=limit, full=full, base_url=base_url,
                sort=query_params.get("sort", ["best"])[0],
            )
            self.send_json(data, status=200 if data.get("success") else 400)

        elif path.startswith("/api/v1/posts/"):
            parts = path.strip("/").split("/")
            if len(parts) == 4 and parts[3].isdigit():
                detail = api_v1_get_post_detail(
                    int(parts[3]), full=full, base_url=base_url,
                    ladder=query_params.get("ladder", ["1"])[0] not in ("0", "false"),
                    # Audit #1: `?warm=1` resolves the auto tier while the
                    # viewer reads the detail screen, so Play answers from
                    # cache. `?audio=` orders the ladder by preferred audio.
                    warm=query_params.get("warm", ["0"])[0] in ("1", "true"),
                    vip=request_is_vip(self.headers, query_params),
                    audio=query_params.get("audio", [""])[0],
                    # Player Fix v2: serve only verified bands (cached
                    # verdict first, bounded live probe when never-checked).
                    verify=True)
                if detail:
                    self.send_json({"success": True, "data": detail})
                else:
                    # Identical to a row that never existed: an adult title must not
                    # be distinguishable from an absent one (API_V2.md §13).
                    self.send_json({"success": False, "error": "Post not found"}, status=404)
            else:
                self.send_json({"error": "Invalid post ID"}, status=400)

        elif path == "/api/v1/live-tv/channels":
            # Live TV channel list, served from the server-side registry so
            # channel URLs stay out of the app bundle and the operator can
            # add / disable a channel with one registry edit. The client
            # gets a signed stream_id per channel and presses it at
            # /api/v1/stream — it never sees the upstream HLS URL.
            # NOTE (deploy): nginx's public allow-list does not yet include
            # the /api/v1/live-tv/ prefix — the gate must add it, same as /api/v2/play
            # was added in live deploy #1, or this answers 403 in public.
            try:
                registry = live_tv.load_registry()
            except ValueError:
                self.send_json({"success": False,
                                "error": "live_tv_unavailable"}, status=503)
                return
            category = query_params.get("category", [None])[0] or None
            channels = live_tv.list_channels(
                registry, category=category, secret=signing_secret())
            self.send_json({"success": True, "channels": channels,
                            "categories": live_tv.list_categories(registry)})

        elif path == "/api/v1/stream":
            source_ref = query_params.get("id", [""])[0]
            # Live-TV handles FIRST: on the public port parse_token runs
            # signed_only, so a TV handle would 400 there if it ever
            # reached the movie branch. A TV press skips the adult check
            # and the quality gate entirely — the registry is curated
            # free-to-air broadcast with no adult category and no
            # 1080p/4K premium distinction.
            tv_channel_id = redact.parse_live_tv_handle(
                source_ref, signing_secret())
            if tv_channel_id is not None:
                redirect_flag = query_params.get("redirect", ["1"])[0]
                try:
                    registry = live_tv.load_registry()
                except ValueError:
                    self.send_json({"success": False,
                                    "error": "live_tv_unavailable"},
                                   status=503)
                    return
                channel = live_tv.get_channel(registry, tv_channel_id)
                if channel is None:
                    # Unknown or disabled channel: same answer as a link
                    # that does not exist.
                    self.send_json({"success": False, "error": "not_found"},
                                   status=404)
                    return
                if not live_tv.playlist_is_live(channel["stream_url"]):
                    # Honest dead-channel answer: the player shows its
                    # unavailable state instead of spinning on a dead URL.
                    self.send_json({"success": False,
                                    "error": "no_playable_source"},
                                   status=404)
                    return
                if redirect_flag in ("1", "true", "yes"):
                    self.send_response(302)
                    self.send_header("Location", channel["stream_url"])
                    self.send_header("Cache-Control", "no-store")
                    for name, value in cors_headers_for(self.headers.get("Origin", "")):
                        self.send_header(name, value)
                    self.send_header("Connection", "close")
                    self.end_headers()
                else:
                    self.send_json({
                        "success": True,
                        "stream_id": redact.mint_live_tv_handle(
                            tv_channel_id, signing_secret()),
                        "kind": "url",
                        "mime_type": "application/vnd.apple.mpegurl",
                    })
                return
            source_id = redact.parse_token(source_ref, signing_secret(),
                                           signed_only=not full)
            if not source_id:
                self.send_json({"error": "Missing or invalid source id parameter 'id'"}, status=400)
                return

            if redact.link_is_adult(int(source_id), DB_PATH):
                # Same answer as a link that does not exist: hidden, not deleted,
                # and never played by an address we did not hand out. Unconditional,
                # on the operator port too — the panel may show that a flagged row
                # exists and what its flag is, and must still not play it.
                self.send_json({"success": False, "error": "not_found"}, status=404)
                return

            blocked = (None if full else
                       quality_gate_block_reason(int(source_id), self.headers,
                                                 query_params))
            if blocked:
                # Audit critical 5, stream half. The operator port is exempt:
                # it is the healing and audit surface, loopback-only by
                # design, and unlike the adult rule a paywall boundary has no
                # reason to blind the person who owns the ledger. 402 says
                # "this is purchasable", which is what the app's VIP screen
                # listens for; the body names no hoster and no URL. The
                # message is plain language for the player (audit #14).
                self.send_json(_plain_stream_error(blocked), status=402)
                return

            redirect_flag = query_params.get("redirect", ["1"])[0]

            # Phase-1 resolved_cache: a fresh, probe-accepted row answers the
            # play as an instant 302 with zero resolver work in the request
            # path. Public port only — the operator port must keep seeing the
            # live resolver's diagnostics. The adult gate above ALWAYS runs
            # first; a cache hit can never bypass it.
            hit = None
            if not full:
                try:
                    import resolved_cache
                    with get_db() as conn:
                        hit = resolved_cache.lookup_cache(conn, int(source_id),
                                                          want="watch")
                except Exception:      # noqa: BLE001
                    hit = None         # a cache problem must never break playback

            if hit:
                if redirect_flag in ("1", "true", "yes"):
                    self.send_response(302)
                    self.send_header("Location", hit["url"])
                    # Same rule as the resolver's 302: it points at somebody
                    # else's signed token — never cacheable, whatever the TTL.
                    self.send_header("Cache-Control", "no-store")
                    for name, value in cors_headers_for(self.headers.get("Origin", "")):
                        self.send_header(name, value)
                    self.send_header("Connection", "close")
                    self.end_headers()
                    return
                # Descriptor from the cache row. `kind` keeps the legacy wire
                # value "url" for files (the shipped app branches on it); only
                # the genuinely-new playlist case differs.
                expires_in = hit["expires_in"]
                if expires_in is None:
                    expires_in = max(0.0, round(hit["reverify_after"] - time.time(), 3))
                self.send_json({
                    "success": True,
                    "stream_id": redact.mint_token(int(source_id), signing_secret()),
                    "kind": "playlist" if hit["kind"] == "playlist" else "url",
                    "mime_type": hit["mime_type"],
                    "file_size_bytes": hit["file_size_bytes"],
                    "resumable": bool(hit["is_resumable"]),
                    "expires_in": expires_in,
                })
                return

            # Stage-2: the stream caller needs watch media — a playlist
            # or a single file. A playlist is never a download, and a
            # page is never either; the resolver enforces both. Coalesced
            # with the detail warm for the same link (see
            # `_resolve_coalesced`): a Play press during the warm joins
            # that resolve instead of starting a second one the 8 s
            # player watchdog would abandon.
            res = _resolve_coalesced(int(source_id), want="watch")

            if res.get("success") and res.get("stale"):
                # Audit critical 2: the v1 resolver answers a failed re-resolve with
                # `success: True` and the last known URL flagged `stale: True`. The
                # download route (v2 contract) refuses exactly that, and this route
                # must not 302 a player at an unverifiable token either: a stale
                # temporary URL is an expired 403, not a stream. The public else
                # below then answers 404 no_playable_source — the client's failover
                # ladder moves to the next source. The operator port still sees the
                # full body, url and `stale` included, which is what healing reads.
                res = dict(res, success=False)

            # On a miss we just paid for a full resolve — bank it for the next
            # player. Never store a stale v1 fallback URL, and a write failure
            # must never change the answer the user gets.
            if (not full and res.get("success") and res.get("url")
                    and not res.get("stale")):
                try:
                    import resolved_cache
                    with get_db() as conn:
                        resolved_cache.record_resolved_cache(conn, int(source_id), res)
                except Exception:      # noqa: BLE001
                    pass

            # The measured-dead counterpart of the bank above — with the
            # qoder12_unprobed distinction: an answer whose service has no
            # unpacker branch (unprobed) measured NOTHING and must not move
            # the circuit, or unsupported hosts would self-break their rows
            # one request at a time on fabricated evidence. Only a probe that
            # actually ran and came back without playable media counts — and
            # it can never change this response.
            elif not full:
                try:
                    import resolved_cache
                    with get_db() as conn:
                        resolved_cache.note_failure_from_probe(
                            conn, int(source_id), res)
                except Exception:      # noqa: BLE001
                    pass

            if res.get("success") and res.get("url"):
                if redirect_flag in ("1", "true", "yes"):
                    # The player follows this and gets bytes; the VM moves none of
                    # them. What the user sees is our own URL.
                    self.send_response(302)
                    self.send_header("Location", res["url"])
                    # This 302 points at somebody else's signed token. A shared
                    # proxy or browser cache that keeps it hands one user's token
                    # to the next, and serves a dead one after its window closes:
                    # never cacheable, whatever the observed TTL says.
                    self.send_header("Cache-Control", "no-store")
                    for name, value in cors_headers_for(self.headers.get("Origin", "")):
                        self.send_header(name, value)
                    self.send_header("Connection", "close")
                    self.end_headers()
                else:
                    if not full:
                        # Used to hand back url + service + source_name, i.e. the
                        # upstream file URL and who hosts it. A caller who wants
                        # bytes follows the 302; nobody needs the hoster's name to
                        # play a video.
                        self.send_json({
                            "success": True,
                            "stream_id": redact.mint_token(int(source_id), signing_secret()),
                            "kind": res.get("playback_type") or "url",
                            "mime_type": res.get("mime_type"),
                            "file_size_bytes": res.get("file_size_bytes"),
                            "resumable": bool(res.get("is_resumable")),
                            # Same key, same type, now sourced from what the hoster
                            # declared (resolve_live_source read Cache-Control /
                            # Expires off the response) instead of from a constant.
                            # When nothing was measured we still quote the 6-hour
                            # temporary-token ceiling the bridges are known to
                            # honour, minus the window the URL has already lived.
                            "expires_in": stream_expires_in(res),
                        })
                    else:
                        self.send_json(res)
            else:
                self.send_json(res if full else _plain_stream_error(
                    "no_playable_source"), status=404)

        elif path == "/api/v1/download":
            source_ref = query_params.get("id", [""])[0]
            source_id = redact.parse_token(source_ref, signing_secret(),
                                           signed_only=not full)
            if not source_id:
                self.send_json({"error": "Missing or invalid source id parameter 'id'"}, status=400)
                return

            if redact.link_is_adult(int(source_id), DB_PATH):
                # Identical to a link that was never minted. Denied on the operator
                # port as well: seeing a flagged row is the panel's job, handing out
                # its bytes is nobody's.
                self.send_json({"success": False, "error": "not_found"}, status=404)
                return

            blocked = (None if full else
                       quality_gate_block_reason(int(source_id), self.headers,
                                                 query_params))
            if blocked:
                # Audit critical 5, download half: the free cap that used to
                # live only in the app. Same 402, same operator exemption as
                # the stream route above — and the same plain-language
                # message, so the app can fail over instead of spinning.
                self.send_json(_plain_stream_error(blocked), status=402)
                return

            # Phase-1 resolved_cache on the download twin. Same ordering rule
            # the stream route proved: the adult gate ABOVE always runs before
            # any cache lookup, and the cache is consulted on the public port
            # only — the operator port keeps the live resolver's diagnostics.
            # A cached row may answer a download ONLY as a single file:
            # lookup_cache(want="download") refuses kind='playlist' rows (a
            # playlist is segments, not a file — the stage-2 rule), and a
            # refused or missing row falls through to the live resolver below.
            # The hit is injected as a resolver-shaped `res`, so the shortener
            # waterfall and attachment-header logic run identically for it:
            # monetization cannot be skipped by a warm cache.
            res = None
            if not full:
                hit = None
                try:
                    import resolved_cache
                    with get_db() as conn:
                        hit = resolved_cache.lookup_cache(
                            conn, int(source_id), want="download")
                except Exception:      # noqa: BLE001
                    hit = None         # a cache fault must not change the answer
                if hit and hit.get("kind") == "file":
                    _now = time.time()
                    res = {
                        "success": True,
                        "id": int(source_id),
                        "url": hit["url"],
                        "cached": True,
                        "cache_hit": True,
                        "mime_type": hit["mime_type"],
                        "file_size_bytes": hit["file_size_bytes"],
                        "is_resumable": bool(hit["is_resumable"]),
                        "is_temporary": hit["category"] == "B",
                        "expires_at": hit["expires_at"],
                        # Measured window when we have one; otherwise our own
                        # honest horizon — never a promised life longer than
                        # the row is guaranteed servable.
                        "expires_in": (hit["expires_in"] if hit["expires_in"]
                                       is not None else
                                       max(0.0, round(hit["reverify_after"] - _now, 3))),
                    }

            if res is None:
                # The honest resolver contract: a bridge that no longer unwraps, or a
                # stale landing page, is a failure — never a "download" of HTML. The
                # v1 stale-URL behaviour exists for the shipped player, and no client
                # of this route has that history.
                # Stage-2: the download caller needs a single file only.
                # A playlist answer here would be segments, not a file.
                # Coalesced like the stream route (see `_resolve_coalesced`).
                res = _resolve_coalesced(int(source_id), v2=True,
                                         want="download")
                # Bank the fresh answer for the next downloader (and player —
                # the watch route accepts file rows too). Stale URLs are never
                # stored, and a cache write must never alter this response.
                if (not full and res.get("success") and res.get("url")
                        and not res.get("stale")):
                    try:
                        import resolved_cache
                        with get_db() as conn:
                            resolved_cache.record_resolved_cache(
                                conn, int(source_id), res)
                    except Exception:      # noqa: BLE001
                        pass
                elif not full:
                    # Measured-dead evidence for the failure circuit — same
                    # rule as the stream route: an unprobed answer (no
                    # unpacker branch matched, nothing measured) must not
                    # count, only a probe that ran and failed may, and it can
                    # never change this answer.
                    try:
                        import resolved_cache
                        with get_db() as conn:
                            resolved_cache.note_failure_from_probe(
                                conn, int(source_id), res)
                    except Exception:      # noqa: BLE001
                        pass

            redirect_flag = query_params.get("redirect", ["1"])[0]

            if res.get("success") and res.get("url"):
                if redirect_flag in ("1", "true", "yes"):
                    # Every bridge redirect is already unwrapped by the resolver;
                    # this is the media address itself. The VM still moves no
                    # bytes, and the caller is told our host, not the hoster's.
                    target = res["url"]
                    shortened = False
                    if not full and not request_is_vip(self.headers, query_params):
                        # A bought direct-download credit skips the shortener
                        # for this one download (daily check-in Build 4): the
                        # token is spent here, whether or not the web marker
                        # is set, because a credit is a direct file, not a web
                        # page. Anything wrong with the token just falls back
                        # to the ordinary shortening — a bad token costs a
                        # direct link, never the download itself.
                        credit_token = query_params.get("credit", [""])[0]
                        credit_used = False
                        if credit_token:
                            try:
                                credit_used = engagement.consume_download_credit(
                                    engagement.default_db_path(), credit_token,
                                    handle=source_ref, credit_secret=signing_secret())
                            except Exception:      # noqa: BLE001
                                credit_used = False
                        # Free tier, WEB PAGE ONLY (owner decision 2026-11-06):
                        # a shortener earns the operator revenue before the
                        # bytes, but only when the request came through the web
                        # download page (`?via=web`). The app's own native
                        # downloads never carry that marker, so they stay
                        # direct however the operator configures the panel.
                        # The cache makes a repeat download free; a shortener
                        # outage falls back to the direct URL rather than
                        # failing the download.
                        via_web = query_params.get("via", [""])[0] == "web"
                        if via_web and not credit_used:
                            try:
                                with get_db() as conn:
                                    shortened_target = shorten_download_url(
                                        target, conn)
                            except Exception:      # noqa: BLE001
                                shortened_target = None
                            if shortened_target:
                                target = shortened_target
                                shortened = True
                    self.send_response(302)
                    self.send_header("Location", target)
                    self.send_header("Cache-Control", "no-store")
                    if not shortened:
                        # A shortened target is a landing page, not the file:
                        # an attachment disposition there would download HTML.
                        filename = download_filename(
                            redact.mint_token(int(source_id), signing_secret()),
                            res.get("mime_type"))
                        self.send_header("Content-Disposition",
                                         f'attachment; filename="{filename}"')
                    for name, value in cors_headers_for(self.headers.get("Origin", "")):
                        self.send_header(name, value)
                    self.send_header("Connection", "close")
                    self.end_headers()
                elif full:
                    self.send_json(res)
                else:
                    self.send_json(download_descriptor(int(source_id), res, base_url))
            else:
                if full:
                    self.send_json(res)
                else:
                    # The resolver's v2 vocabulary is already public: an unknown
                    # handle and a dead link both answer 404, and saying which is
                    # which leaks nothing (the adult gate above already returns
                    # not_found). Anything unrecognised collapses to one name.
                    code = res.get("code") or res.get("error")
                    if code not in ("not_found", "no_playable_source"):
                        code = "no_playable_source"
                    self.send_json(
                        _plain_stream_error(code)
                        if code == "no_playable_source" else
                        {"success": False, "error": code}, status=404)

        elif path == "/api/v1/art":
            self._serve_art(query_params, full=full)

        elif path == "/api/v1/rules":
            self.send_json(api_v1_rules())

        elif path == "/api/v1/app/remote-config":
            # The phone's payment and sponsor card: PKR pricing, the JazzCash /
            # EasyPaisa / Raast handles it prints beside a Copy button, the ad
            # unit ids, and which link shorteners are live. Built by
            # `admin_panel`, which owns those settings, and the same on both
            # ports — the shortener API tokens in the row are masked there and
            # absent here, so this body has no richer second version to leak. A
            # client that shortened with the token itself would hand every user
            # of this endpoint the operator's payout account.
            _ensure_schema()
            with get_db() as conn:
                payload = admin_panel.remote_config(conn)
                # The panel feed rides the same body the app already polls:
                # sections the operator built, broadcasts it published, works
                # it hid, the theme knobs it set, and the tabs it ordered. No
                # new route, so the public allow-list does not change. Unwired
                # means three empty lists plus the default theme and the
                # default tabs, and the app keeps its own rails; the keys are
                # always present so the client contract never depends on the
                # panel being up.
                feed = panel_feed.load_panel_feed(conn)
                all_ids = [int(r["id"]) for s in feed["sections"]
                           for r in s["rows"]]
                subtitled = _subtitled_posts(conn, all_ids)

                def _project_panel_post(row):
                    item = redact.project(row, "post_brief")
                    item.update(_art_pair(row, base_url))
                    item["work_ref"] = _work_ref(row)
                    item["subtitled"] = bool(
                        subtitled.get(int(row["id"]), False))
                    return item

                payload["sections"] = [
                    {"key": s["key"], "title": s["title"],
                     "items": [_project_panel_post(r) for r in s["rows"]]}
                    for s in feed["sections"]
                ]
                payload["broadcasts"] = feed["broadcasts"]
                payload["hidden_work_ids"] = feed["hidden_work_ids"]
                payload["theme"] = panel_feed.read_theme()
                payload["tabs"] = panel_feed.read_tabs()
                payload["disclaimer"] = panel_feed.read_disclaimer()
                payload["free_quality_cap"] = panel_feed.read_free_quality_cap()
                payload["min_version_code"] = panel_feed.read_min_version()
                # The force-update block rides the same body: the latest
                # APK the operator published, whether an older app must
                # update, the copy for it, the brand colours and the region
                # order. Read from the PUBLISHED snapshot, so a draft
                # force-update never reaches a phone.
                payload["force_update"] = panel_feed.read_force_update()
                # A paused feature is off, whatever the catalog row says:
                # the operator paused it, and the app must not offer it.
                _paused = panel_feed.paused_features()
                _flags = payload.get("feature_flags")
                if isinstance(_flags, dict):
                    for _feature in _paused:
                        if _feature in _flags:
                            _flags[_feature] = False
            self.send_json(redact.scrub(payload),
                           extra_headers=[("Cache-Control", "public, max-age=60")])

        elif path == "/api/v1/stats":
            _ensure_schema()
            with get_db() as conn:
                stats_data = _get_cached_stats(conn)
            self.send_json(redact.project(stats_data, "stats"))

        elif path == "/favicon.ico":
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.send_header("Connection", "close")
            self.end_headers()

        elif path == "/client" or path == "/mobile":
            self.send_bytes(render_mobile_client(full).encode("utf-8"),
                            content_type="text/html; charset=utf-8")

        elif path == "/" or path == "/index.html":
            # The DB explorer names sites and upstream pages by design — that is
            # what it is for — so it lives on the loopback port only. The public
            # port gets a page that says what the service is.
            page = (DASHBOARD_HTML if full else render_public_landing())
            self.send_bytes(page.encode("utf-8"), content_type="text/html; charset=utf-8")

        else:
            self.send_bytes(b"Not Found", content_type="text/plain", status=404)

    def do_HEAD(self):
        """HEAD is GET with no body, and `/api/v1/art` already writes none — it
        answers 302 with a `Location`, CORS, and `Cache-Control`. A client that
        HEADs a poster URL (any CDN-aware loader doing cache validation) therefore
        gets the redirect instead of the stdlib's 501 for an unhandled verb.

        Only `/api/v1/art` is dispatched here: every other path keeps the base
        class's 501, because the routes that do write a body on GET must not
        silently advertise a zero-length HEAD that disagrees with the GET."""
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query_params = urllib.parse.parse_qs(parsed.query)
        full = bool(getattr(self.server, "operator", False))
        if full:
            if not self._operator_gate():
                return
        if not full and not self._public_gate(path, "HEAD"):
            return
        if path == "/api/v1/art":
            self._serve_art(query_params, full=full)
            return
        self.send_error(501, "Unsupported method ('HEAD')")

    def _contact_intake(self):
        """`POST /api/v1/contact` — the public contact form, no login.

        One JSON body: `category` (one of the panel's five), `subject`,
        `body`, and an optional `account_hint` (an email the viewer leaves
        so the operator can reply). The message is stored in the panel's
        `contact_messages` table by `contact_intake`, under the panel's own
        validation and masking, so it lands in the same inbox the operator
        already triages. Answers the v1 shape: `{"success": true}` on store,
        `invalid_params` (400) for a bad category or an empty body,
        `unavailable` (503) when the panel inbox is not wired or locked —
        an honest retry-later, never a swallowed message — and
        `rate_limited` (429) when one address already sent ten messages
        today. A filled `website` field (the honeypot a human form never
        sends) is answered with success and written nowhere.
        """
        payload, code = api_v2.read_body(self)
        if payload is None:
            self.send_json({"success": False, "error": code or "invalid_params"},
                           status=400)
            return
        ok, result = contact_intake.submit_contact(
            category=payload.get("category"),
            subject=payload.get("subject", ""),
            body=payload.get("body", ""),
            account_hint=payload.get("account_hint"),
            client_ip=redact.client_ip(self),
            honeypot=payload.get("website"),
        )
        if not ok:
            status = {"unavailable": 503, "rate_limited": 429}.get(result, 400)
            self.send_json({"success": False, "error": result}, status=status)
            return
        self.send_json({"success": True})

    def do_POST(self):
        """The v2 write surface (§12): `/play`, link reports, learned offsets,
        the account writes that put a favorite or a resume point on the server, and
        the merchant's payment-SMS callback (`_merchant_relay`).

        Same edge as `do_GET` — operator routes 404, one token bucket, the
        `RateLimit-*` triple — because a POST is the same attack surface wearing a
        different verb.
        """
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query_params = urllib.parse.parse_qs(parsed.query)
        full = bool(getattr(self.server, "operator", False))
        if full:
            if self._operator_login(path, "POST"):
                return
            if not self._operator_gate():
                return
        if not full and not self._public_gate(path, "POST"):
            return
        if path.startswith(OPERATOR_ONLY_PREFIXES):
            if not full:
                self.send_json({"success": False, "error": "not_found"}, status=404)
                return
            # `admin_panel` decides which action consumes a body; only it knows,
            # and only the mount may read one. Refusals stay in the module's own
            # problem vocabulary rather than gaining a second shape here.
            body = None
            if admin_panel.takes_body(path):
                content_type = str(self.headers.get("Content-Type", "") or "")
                if admin_panel.form_encoded(content_type):
                    # The payment queue's Approve/Reject buttons are real HTML
                    # forms, so a review works with JavaScript off. The same
                    # ceiling as JSON applies: never read more than the body cap.
                    try:
                        length = int(self.headers.get("Content-Length") or 0)
                    except (TypeError, ValueError):
                        length = 0
                    length = max(0, min(length, api_v2.MAX_BODY_BYTES))
                    body = admin_panel.parse_form_body(self.rfile.read(length))
                else:
                    body, body_error = api_v2.read_body(self)
                    if body_error:
                        self.send_triple(admin_panel.refuse_bad_body(path))
                        return
            answered = admin_panel.route_post(
                path, query_params, db_path=DB_PATH,
                peer_address=self.client_address[0],
                token_header=self.headers.get("Authorization", ""),
                body=body, state_db_path=accounts_api.state_db(),
                cookie_header=self.headers.get("Cookie", ""),
                accepts_html=self._accepts_html(),
                csrf_header=self.headers.get(admin_panel.CSRF_HEADER, ""))
            if answered is not None:
                self.send_triple(answered)
                return
        if path == payments.WEBHOOK_PATH:
            # Answered here, ahead of both dispatchers, because neither of them
            # knows this path's shape: `accounts_api` routes only `/api/v2/account*`
            # and `api_v2` would hand an unknown head to its `not_found`
            # fall-through. The credential is the merchant secret rather than a sync
            # key, so this is also the one public POST that is authorized before its
            # body is read. See `_merchant_relay` for why it is not an `admin_panel`
            # route.
            self._merchant_relay(path)
            return
        if accounts_api.is_account(path):
            _ensure_schema()
            payload, code = api_v2.read_body(self)
            if payload is None:
                api_v2.problem(self, code=code or "invalid_params",
                               rid=api_v2.request_id(), instance=path)
                return
            answered = accounts_api.route_post(
                path, payload, db_path=accounts_api.state_db(), catalog_path=DB_PATH,
                secret=signing_secret(), headers=self.headers,
                client_ip=redact.client_ip(self))
            if answered is not None:
                self.send_triple(answered)
                return
        if path == "/api/v1/contact":
            # The public contact form: one JSON body, no login, no sync key —
            # the message lands in the panel's inbox under the panel's own
            # rules (`contact_intake`). Answered ahead of the v2 dispatcher
            # because this is a v1 route and `api_v2` would 404 it.
            self._contact_intake()
            return
        if api_v2.is_v2(path):
            _ensure_schema()
            if api_v2.route_post(self, path, query_params, db_path=DB_PATH,
                                 operator=full, base_url=_public_base(self),
                                 secret=signing_secret()):
                return
        self.send_json({"success": False, "error": "not_found"}, status=404)

    def log_message(self, format, *args):
        pass


def export_standalone_html(output_file: str = "database_view.html") -> str:
    """A self-contained dashboard snapshot for the operator's own machine.

    Always `full`: the badges and copy-the-upstream-URL buttons are the reason to
    open this file, and it never leaves the box — the server has no static route
    that could hand it to a client, and it is gitignored.

    Counters are `stats="full"` here — this is the one caller allowed to ask for
    the live scan, because it is an explicit CLI snapshot an operator waits for,
    not a page that reloads itself."""
    payload = fetch_database_payload(full=True, base_url=PUBLIC_BASE_URL,
                                     stats="full")
    json_str = json.dumps(payload, ensure_ascii=False).replace("</script>", "<\\/script>")

    standalone = DASHBOARD_HTML.replace(
        "fetchData();",
        f"dbData = {json_str}; renderStats(); renderPosts(); renderPager();"
    ).replace(
        "async function fetchData(query, page, statsMode) {",
        "async function fetchData(query, page, statsMode) { return; "
    )

    out_path = BASE_DIR / output_file
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(standalone)
    return str(out_path)


def make_server(host: str, port: int, operator: bool):
    """One handler class, two policies. The policy lives on the *server object*,
    because anything a request carries (header, query, path prefix) is something
    a request can forge — a port it cannot."""
    server = ThreadedHTTPServer((host, port), DashboardHandler)
    server.operator = operator
    return server


def start_server(port: int = 8080, host: str = "127.0.0.1",
                 operator_port: int | None = None):
    import threading
    _ensure_schema()
    server = make_server(host, port, operator=False)
    display_host = "127.0.0.1" if host == "0.0.0.0" else host
    url = f"http://{display_host}:{port}"

    internal = None
    internal_host = os.environ.get("RADD_INTERNAL_HOST", "127.0.0.1")
    try:
        internal = make_server(internal_host, operator_port or OPERATOR_PORT,
                               operator=True)
    except OSError as ex:
        print(f"[i] operator dashboard unavailable: {ex}")

    print("\n" + "=" * 65)
    print("🚀 Fast_Fetch Database Viewer & Site Explorer Running!")
    print(f"👉 Public API + web client: {url}")
    if internal:
        print(f"🔧 Operator dashboard (full provenance, loopback only): "
              f"http://{internal_host}:{internal.server_address[1]}")
    print(f"📁 Database: {DB_PATH}")
    print(f"⚡ Press Ctrl+C to stop the server")
    print("=" * 65 + "\n", flush=True)

    try:
        import webbrowser
        webbrowser.open(url)
    except Exception:
        pass

    if internal:
        threading.Thread(target=internal.serve_forever, daemon=True).start()

    # Scheduled background maintenance (Session 123): one daemon thread runs
    # a bounded propagate + warm + heal tick every few hours, so the healing
    # daemon and link_state.propagate() no longer wait for a manual CLI run.
    # Env-gated (`RADD_MAINTENANCE=off` disables it); a failure to start it
    # never stops the server from serving.
    try:
        import maintenance
        maintenance.start_maintenance_thread()
    except Exception as ex:      # noqa: BLE001 — serving matters more than the tick
        print(f"[i] scheduled maintenance unavailable: {ex}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[i] Server stopped.")
    finally:
        server.server_close()
        if internal:
            internal.shutdown()
            internal.server_close()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 8080
    start_server(port)
