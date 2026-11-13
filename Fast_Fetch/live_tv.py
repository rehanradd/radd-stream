"""Live TV channel registry — server-side, operator-controllable.

The app's Live TV tab never ships channel URLs. It renders whatever
``GET /api/v1/live-tv/channels`` serves, and plays a channel by pressing
``/api/v1/stream?id=<signed handle>`` through the existing player, exactly
like a movie. The registry file lives next to this module
(``live_tv_registry.json``), modelled on ``domain_registry.json`` v2.

Every seeded channel was probed live from the Oracle VM with curl +
ffprobe (real video + audio in the playlist, 2026-11-09 ~00:25 PKT).
``enabled`` is the operator's switch: only broadcaster-published streams
(official / public-broadcaster / official playout / FAST / official CDN)
ship enabled. Verified-playing third-party restreams are seeded disabled
with the reason, so the endpoint hides them until an operator enables them
with one registry edit. A disabled channel never plays: the stream route
404s it, and the list endpoint never names it.

Stdlib only.
"""

import json
import os
import time
import urllib.error
import urllib.request

import redact

REGISTRY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "live_tv_registry.json")

#: Categories a channel may carry. Only categories with real verified
#: channels are seeded; the app renders chips from what the endpoint
#: actually serves, so adding a category here is enough to show it.
#: "movies" arrived with the iptv-org importer (import_iptv_org.py):
#: linear movie channels are a real category in that data. "education"
#: arrived with it too: DD Kisan, Gyandarshan and KITE Victers are real
#: linear education channels, not entertainment.
ALLOWED_CATEGORIES = frozenset({
    "news", "sports", "entertainment", "music", "kids", "religious",
    "travel", "movies", "education",
})

#: The probe that decides whether a channel plays right now: a short GET of
#: the playlist, following redirects (a broadcaster CDN 302s first), that
#: must answer 200 with a real ``#EXTM3U`` body. No segment is fetched.
PROBE_TIMEOUT_SECONDS = 5.0

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_CACHE = {"mtime": None, "path": None, "registry": None}


def _fail(reason):
    raise ValueError("live_tv_registry: " + reason)


def validate_registry(data):
    """Fail closed on a malformed registry — a bad file serves nothing.

    Checks the shape the endpoint and the stream route rely on: unique
    integer ids, known categories, https playlist URLs, and no adult
    category anywhere (live TV is curated news/sports/entertainment).
    """
    if not isinstance(data, dict):
        _fail("top level must be an object")
    channels = data.get("channels")
    if not isinstance(channels, list) or not channels:
        _fail("channels must be a non-empty list")
    seen_ids = set()
    for entry in channels:
        if not isinstance(entry, dict):
            _fail("each channel must be an object")
        channel_id = entry.get("id")
        if not isinstance(channel_id, int) or isinstance(channel_id, bool):
            _fail("channel id must be an integer")
        if channel_id in seen_ids:
            _fail("duplicate channel id %r" % (channel_id,))
        seen_ids.add(channel_id)
        if not isinstance(entry.get("name"), str) or not entry["name"].strip():
            _fail("channel %r must have a name" % (channel_id,))
        if entry.get("category") not in ALLOWED_CATEGORIES:
            _fail("channel %r has unknown category %r"
                  % (channel_id, entry.get("category")))
        if not isinstance(entry.get("country"), str) or not entry["country"]:
            _fail("channel %r must have a country" % (channel_id,))
        if not isinstance(entry.get("language"), str) or not entry["language"]:
            _fail("channel %r must have a language" % (channel_id,))
        logo = entry.get("logo_url")
        if not isinstance(logo, str) or not logo.startswith("https://"):
            _fail("channel %r must have an https logo_url" % (channel_id,))
        stream_url = entry.get("stream_url")
        # https in production. Plain http is allowed only on loopback, so
        # the test fixture can point at a local fake playlist server; a
        # real channel URL over plain http is rejected.
        loopback = (stream_url.startswith("http://127.0.0.1")
                    or stream_url.startswith("http://localhost"))
        if (not isinstance(stream_url, str)
                or not (stream_url.startswith("https://") or loopback)
                or ".m3u8" not in stream_url):
            _fail("channel %r must have an https .m3u8 stream_url"
                  % (channel_id,))
        if not isinstance(entry.get("enabled"), bool):
            _fail("channel %r must have a boolean enabled" % (channel_id,))
        if not isinstance(entry.get("source"), str) or not entry["source"]:
            _fail("channel %r must have a source basis" % (channel_id,))
    return data


def load_registry(registry_path=None):
    """Read + validate the registry, cached by file mtime.

    An operator edit to the JSON is picked up on the next request without a
    restart. A missing or malformed file raises — the endpoint answers
    ``live_tv_unavailable`` instead of serving a half-loaded list.
    """
    path = registry_path or REGISTRY_PATH
    try:
        mtime = os.path.getmtime(path)
    except OSError as exc:
        raise ValueError("live_tv_registry: cannot read %s (%s)"
                         % (path, exc)) from exc
    if _CACHE["path"] == path and _CACHE["mtime"] == mtime \
            and _CACHE["registry"] is not None:
        return _CACHE["registry"]
    with open(path, encoding="utf-8") as handle:
        data = validate_registry(json.load(handle))
    _CACHE.update({"path": path, "mtime": mtime, "registry": data})
    return data


def list_channels(registry, category=None, secret=None):
    """Public projection of the enabled channels, newest-first by id order.

    The upstream ``stream_url`` and the internal ``source`` basis never
    leave the server: the client gets a signed ``stream_id`` handle and
    presses it at ``/api/v1/stream``. ``category`` filters exactly; an
    unknown category returns an empty list, never an error.
    """
    out = []
    for entry in registry["channels"]:
        if not entry["enabled"]:
            continue
        if category is not None and entry["category"] != category:
            continue
        out.append({
            "id": entry["id"],
            "name": entry["name"],
            "category": entry["category"],
            "country": entry["country"],
            "language": entry["language"],
            "logo_url": entry["logo_url"],
            "stream_id": (redact.mint_live_tv_handle(entry["id"], secret)
                          if secret is not None else None),
        })
    return out


def list_categories(registry):
    """Categories that actually have an enabled channel, in first-seen order."""
    seen = []
    for entry in registry["channels"]:
        if entry["enabled"] and entry["category"] not in seen:
            seen.append(entry["category"])
    return seen


def get_channel(registry, channel_id):
    """The raw registry entry for an enabled channel id, else ``None``.

    Disabled and unknown ids are indistinguishable here on purpose: the
    stream route 404s both, so a disabled channel can never be played by
    guessing its id.
    """
    try:
        wanted = int(channel_id)
    except (TypeError, ValueError):
        return None
    for entry in registry["channels"]:
        if entry["id"] == wanted and entry["enabled"]:
            return entry
    return None


def playlist_is_live(stream_url, timeout=PROBE_TIMEOUT_SECONDS):
    """True when the channel's playlist answers 200 with a real ``#EXTM3U``.

    This is the same bar the VM probes used (curl + ffprobe). A master
    playlist counts: the player resolves its variants. Any transport
    error, non-200 status, or non-playlist body is dead — the stream route
    then answers an honest 404 instead of handing the player a dead URL.
    """
    try:
        request = urllib.request.Request(
            stream_url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            if resp.status != 200:
                return False
            body = resp.read(65536)
    except (urllib.error.URLError, OSError, ValueError):
        return False
    return b"#EXTM3U" in body


def clear_cache():
    """Test hook: forget the mtime-cached registry."""
    _CACHE.update({"mtime": None, "path": None, "registry": None})


if __name__ == "__main__":
    registry = load_registry()
    started = time.time()
    print("channels: %d, enabled: %d, categories: %s"
          % (len(registry["channels"]),
             sum(1 for c in registry["channels"] if c["enabled"]),
             ", ".join(list_categories(registry))))
    print("probe of first enabled channel:",
          playlist_is_live(get_channel(
              registry, next(c["id"] for c in registry["channels"]
                             if c["enabled"]))["stream_url"]),
          "in %.2fs" % (time.time() - started))
