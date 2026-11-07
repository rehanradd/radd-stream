#!/usr/bin/env python3
"""Stage-1 proven-host resolver for Radd Stream (stdlib only).

Covers ONLY the hosts the research actually proved, from the host-knowledge
notes (patterns only — this file stores no keys, file codes, tokens, or
signed URLs, and it never stores a resolved signed URL: every resolve runs
fresh at play time):

- watch: iqsmart chain (StreamHG), modiplay backends (StreamHG + Vidrift),
  vidrift direct, vidbolt, filmu movies, vibuxer signed HLS route.
- download: PixelDrain (resumable) and fastdl.beer (real file, NOT
  resumable — it ranks below every resumable host).

Rules this module enforces, wherever it is used:

1. Classify by the link's REAL host, never by the database service label.
   Mirror labels (gd-mirror, gdmirror, filesforever-*) are iqsmart-family
   shapes only when their link host says so; a label alone proves nothing.
2. Rank by BACKEND, never by front-end. modiplay resolving to StreamHG is
   the same backend as iqsmart, and modiplay resolving to Vidrift is the
   same backend as vidrift direct — neither pair counts as two independent
   backups. vidbolt and filmu/vidly share a media-host family, so they sit
   in one independence group ("rousav") and a truly different backend is
   always preferred as the second backup.
3. A copy is playable only after a capped probe of the media itself:
   a playlist that answers 200 with renditions, or a file that answers
   206 (resumable) / 200 with a video mime (playable, resumable only with
   Range support). An HTML page, shell, landing page, or bridge page is
   NEVER a video file, however cheerful its 200 looks.
4. Failure classes are honest and distinct: a 404 on the media is a dead
   file for that copy; a 403 is a block, not death; a 429 is rate-limited,
   not dead; a timeout/empty reply is a transport failure, not death; a
   signed master that 403s with a missing-key shape is gated, not dead.
   Only a failed probe keeps a copy out of a band — a stamped status in
   the ledger never ranks on its own, and a stamped-dead copy that passes
   a fresh probe is healed, not kept dead.
5. filmu series is NEVER served from static evidence: its signed master
   403s on a plain server fetch, so the server-side answer for a filmu
   series copy is "server-side unverified", never the signed link.
6. No probe ever full-reads a file: file probes are Range bytes=0-511
   and every body read is capped. HEAD is a hint only, never a verdict.
7. Quality bands come from the release, never from a playlist rendition:
   wide (2.40:1) renditions would mis-band on height alone, so this module
   reports rendition sizes and lets the caller band by release fields.
   HDR is a flag, never a band (that fix is a later slice, not this one).
"""

from __future__ import annotations

import base64
import json
import re
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "Mozilla/5.0"
DEFAULT_TIMEOUT = 15.0
MAX_BODY_BYTES = 524288
FILE_PROBE_BYTES = 512

#: Backends this module can resolve. "modiplay" is a front-end, not a
#: backend: resolve_copy returns the backend it actually resolved to.
STAGE1_BACKENDS = frozenset({
    "streamhg", "vidrift", "vidbolt", "vidly", "vibuxer",
    "pixeldrain", "fastdl-beer",
})

#: Independence groups: two copies in one group are one backup, not two.
INDEPENDENCE_GROUP = {
    "streamhg": "streamhg",
    "vidrift": "vidrift",
    "vidbolt": "rousav",
    "vidly": "rousav",
    "vibuxer": "vibuxer",
    "pixeldrain": "pixeldrain",
    "fastdl-beer": "fastdl-beer",
}

#: Watch tie-break order between backends (only after probe evidence).
WATCH_PREFERENCE = (
    "streamhg", "vidrift", "vidbolt", "vidly", "vibuxer",
    "pixeldrain", "fastdl-beer",
)

#: Download order: resumable first (handled by the sort), then this order.
#: fastdl.beer is last on purpose — its files ignore Range.
DOWNLOAD_PREFERENCE = ("pixeldrain", "fastdl-beer")

_MEDIA_SUFFIXES = (
    ".mp4", ".m4v", ".mkv", ".webm", ".mov", ".avi", ".wmv", ".flv",
    ".ts", ".m3u8", ".mpd", ".mp3", ".m4a", ".aac",
)

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


def download_extension_for(mime_type, url: str = "") -> str:
    """Extension for a download name: mime first, URL suffix as fallback.

    A known video mime never yields ".bin". ".bin" survives only when
    neither the mime nor the media URL names a known container.
    """
    mime = str(mime_type or "").split(";", 1)[0].strip().lower()
    if mime in _DOWNLOAD_EXTENSIONS:
        return _DOWNLOAD_EXTENSIONS[mime]
    path = urllib.parse.urlsplit(str(url or "")).path.lower()
    for suffix in _MEDIA_SUFFIXES:
        if path.endswith(suffix):
            return suffix
    return ".bin"


class FetchResult:
    """One HTTP exchange, body already capped. status 0 == transport failure."""

    def __init__(self, status=0, content_type="", body=b"", headers=None,
                 final_url="", error=""):
        self.status = status
        self.content_type = content_type or ""
        self.body = body or b""
        self.headers = headers or {}
        self.final_url = final_url or ""
        self.error = error or ""

    def text(self) -> str:
        return self.body.decode("utf-8", errors="ignore")


def default_fetch(url: str, referer: str | None = None, method: str = "GET",
                  range_bytes: tuple[int, int] | None = None,
                  data: dict | None = None,
                  timeout: float = DEFAULT_TIMEOUT) -> FetchResult:
    """Real network fetch: capped reads, redirects followed, no JS, no login."""
    headers = {"User-Agent": USER_AGENT}
    if referer:
        headers["Referer"] = referer
    if range_bytes is not None:
        headers["Range"] = f"bytes={range_bytes[0]}-{range_bytes[1]}"
    body_data = None
    if data is not None:
        body_data = urllib.parse.urlencode(data).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        if method == "GET":
            method = "POST"
    req = urllib.request.Request(url, headers=headers, method=method,
                                 data=body_data)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(MAX_BODY_BYTES + 1)[:MAX_BODY_BYTES + 1]
            return FetchResult(
                status=resp.status,
                content_type=resp.headers.get("Content-Type", ""),
                body=body,
                headers={k.lower(): v for k, v in resp.headers.items()},
                final_url=resp.geturl(),
            )
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read(MAX_BODY_BYTES + 1)[:MAX_BODY_BYTES + 1]
        except Exception:
            body = b""
        return FetchResult(status=exc.code, content_type="",
                           body=body, headers={},
                           error=f"http_{exc.code}")
    except Exception as exc:  # timeout, DNS, reset, empty reply: transport
        return FetchResult(status=0, error=f"transport:{type(exc).__name__}")


def _is_video_mime(content_type: str) -> bool:
    ct = (content_type or "").split(";", 1)[0].strip().lower()
    return ct.startswith("video/") or ct.startswith("audio/")


def classify_probe(result: FetchResult, url: str = "") -> dict:
    """Turn one probe exchange into an honest verdict (never a guess).

    Returns ok/kind/mime/size/resumable/renditions/failure. ``failure``
    is None on a pass; otherwise one of: dead_file, blocked, challenge,
    signed_gated, rate_limited, transport, html_shell, empty_playlist,
    unverified. Only dead_file means this copy's media is gone.
    """
    status = result.status
    ct = (result.content_type or "").split(";", 1)[0].strip().lower()
    body = result.body or b""
    text = body.decode("utf-8", errors="ignore")
    headers = result.headers or {}
    size = None
    try:
        if headers.get("content-length"):
            size = int(headers["content-length"])
    except (TypeError, ValueError):
        size = None

    if status == 0 or result.error.startswith("transport"):
        return {"ok": False, "kind": None, "mime": None, "size": size,
                "resumable": False, "renditions": [], "failure": "transport"}
    if status in (404, 410):
        return {"ok": False, "kind": None, "mime": None, "size": size,
                "resumable": False, "renditions": [], "failure": "dead_file"}
    if status == 429:
        return {"ok": False, "kind": None, "mime": None, "size": size,
                "resumable": False, "renditions": [],
                "failure": "rate_limited"}
    if status == 403:
        lowered = text.lower()
        if "missingkey" in lowered or "missing key" in lowered:
            failure = "signed_gated"
        elif any(m in lowered for m in ("just a moment", "attention required",
                                        "turnstile", "cf-challenge",
                                        "verify you are human")):
            failure = "challenge"
        else:
            failure = "blocked"
        return {"ok": False, "kind": None, "mime": None, "size": size,
                "resumable": False, "renditions": [], "failure": failure}

    stripped = text.lstrip()
    if "mpegurl" in ct or stripped.startswith("#EXTM3U"):
        renditions = [(int(w), int(h)) for w, h in
                      re.findall(r"RESOLUTION=(\d+)x(\d+)", text)]
        if renditions:
            return {"ok": True, "kind": "playlist",
                    "mime": "application/vnd.apple.mpegurl", "size": size,
                    "resumable": False, "renditions": renditions,
                    "failure": None}
        if "#EXTINF" in text:
            return {"ok": True, "kind": "playlist",
                    "mime": "application/vnd.apple.mpegurl", "size": size,
                    "resumable": False, "renditions": [],
                    "failure": None}
        return {"ok": False, "kind": None, "mime": None, "size": size,
                "resumable": False, "renditions": [],
                "failure": "empty_playlist"}

    if status in (200, 206) and (_is_video_mime(ct) or
                                 (ct == "application/octet-stream" and
                                  urllib.parse.urlsplit(url).path.lower().endswith(_MEDIA_SUFFIXES))):
        ranges = (headers.get("accept-ranges") or "").lower()
        resumable = status == 206 or "bytes" in ranges
        return {"ok": True, "kind": "file",
                "mime": ct or None, "size": size, "resumable": resumable,
                "renditions": [], "failure": None}

    if status == 200 and ("text/html" in ct or "<html" in text.lower()[:2048]):
        return {"ok": False, "kind": None, "mime": None, "size": size,
                "resumable": False, "renditions": [],
                "failure": "html_shell"}
    return {"ok": False, "kind": None, "mime": None, "size": size,
            "resumable": False, "renditions": [], "failure": "unverified"}


def probe_media(url: str, referer: str | None = None,
                kind_hint: str = "playlist",
                fetch=default_fetch) -> dict:
    """Probe one media address with a capped read. Files: Range only."""
    if kind_hint == "file":
        result = fetch(url, referer, range_bytes=(0, FILE_PROBE_BYTES))
    else:
        result = fetch(url, referer)
    verdict = classify_probe(result, url)
    verdict["probed_url_host"] = urllib.parse.urlsplit(url).netloc
    return verdict


def clean_url(url: str) -> str:
    """Strip/encode stray whitespace inside a saved URL (vibuxer defect:
    most saved rows carry embedded whitespace and must be trimmed/encoded
    before any fetch, never fetched verbatim)."""
    cleaned = "".join(str(url or "").split())
    return cleaned


def _host_of(url: str) -> str:
    try:
        return urllib.parse.urlsplit(str(url or "")).netloc.lower().split(":")[0]
    except Exception:
        return ""


def classify_backend(url_a: str = "", url_b: str = "") -> str:
    """Backend for a saved link, by real host — never by service label.

    url_a is the saved (source) address; url_b is a previously resolved
    address, used only when url_a names no known host. Returns "unknown"
    when neither names a stage-1 host.
    """
    for url in (url_a, url_b):
        host = _host_of(url)
        path = urllib.parse.urlsplit(str(url or "")).path or ""
        if not host:
            continue
        if host == "pixeldrain.com" or "/api/file/" in path:
            return "pixeldrain"
        if host.endswith("fastdl.beer"):
            return "fastdl-beer"
        if host == "embed.vidrift.net":
            return "vidrift"
        if host == "vidbolt.xyz":
            return "vidbolt"
        if host in ("embed.filmu.in", "vidly.pro") or host.endswith(".vidly.pro"):
            return "vidly"
        if host == "streams.iqsmartgames.com":
            return "streamhg"
        if host == "pro.iqsmartgames.com" and path.startswith("/evid/"):
            return "streamhg"
        if "modiplay" in host:
            return "modiplay"
        if host == "vibuxer.com" or host.endswith(".vibuxer.com"):
            return "vibuxer"
        if host == "filesforever.link":
            return "filesforever"
    return "unknown"


def independence_group(backend: str) -> str:
    return INDEPENDENCE_GROUP.get(backend, backend)


# ── packer unpacking (Dean Edwards packer, as the players ship it) ──────────

def _b36(number: int, base: int) -> str:
    chars = "0123456789abcdefghijklmnopqrstuvwxyz"
    if number == 0:
        return "0"
    out = ""
    while number > 0:
        out = chars[number % base] + out
        number //= base
    return out


def unpack_packer(body: str) -> str:
    """Unpack one eval(p,a,c,k) block, or "" when the page has none.

    Pure regex + substitution: no JS engine, no page execution.
    """
    try:
        match = re.search(
            r"eval\(function\(p,a,c,k,e,d\).*?return p\}\('(.*?)',(\d+),(\d+),'([^']*)'\.split",
            body, re.S)
        if not match:
            return ""
        payload, base, count, words = (match.group(1), int(match.group(2)),
                                       int(match.group(3)),
                                       match.group(4).split("|"))
        out = payload
        for index in range(count - 1, -1, -1):
            if index < len(words) and words[index]:
                out = re.sub(r"\b" + _b36(index, base) + r"\b",
                             words[index], out)
        return out
    except Exception:
        return ""


def extract_hls_links(text: str) -> dict:
    """hls2/hls3/hls4 values from an unpacked (or plain) player page."""
    links = {}
    block = re.search(r"links\s*=\s*\{([^}]+)\}", text)
    source = block.group(1) if block else text
    for key, value in re.findall(r'"(hls\d+)"\s*:\s*"([^"]+)"', source):
        links[key] = value
    return links


def _letvar(page: str, name: str) -> str:
    match = re.search(r'let ' + re.escape(name) + r'\s*=\s*"([^"]+)"', page)
    return match.group(1) if match else ""


def _extract_json_array(body: str, key: str):
    """Bracket-matched JSON array for `key` (vidrift orionStreams).

    A plain regex fails on the nested arrays, so the matcher walks the
    string tracking quotes/escapes and bracket depth. Returns the parsed
    value, None when the value is null/absent, or "unparsed" on bad JSON.
    """
    start = body.find('"' + key + '":')
    if start < 0:
        return None
    if body[start:].lstrip().startswith('"'):
        pass
    rest = body[start:]
    if rest[len('"' + key + '":'):].lstrip().startswith("null"):
        return None
    i = body.find("[", start)
    if i < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    for j in range(i, len(body)):
        ch = body[j]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(body[i:j + 1])
                    except Exception:
                        return "unparsed"
    return None


# ── unwrappers: each returns (backend, candidates, failure) ────────────────
# candidates: [{"url": ..., "referer": ..., "kind_hint": "playlist"|"file"}]
# failure: None on success, otherwise a failure-class string (never a URL).

def _unwrap_iqsmart(saved_url: str, fetch) -> tuple:
    embed = saved_url
    page = fetch(embed)
    if page.status != 200:
        return "streamhg", [], ("blocked" if page.status == 403 else
                                "transport" if page.status == 0 else "unverified")
    html = page.text()
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(embed).query)
    keys = query.get("key") or [""]
    key = keys[0]
    final_id, id_type = _letvar(html, "FinalID"), _letvar(html, "idType")
    if not final_id or not id_type or not key:
        return "streamhg", [], "unverified"
    host = urllib.parse.urlsplit(embed).netloc
    if "myseriesapi" in html:
        season, epname = _letvar(html, "season"), _letvar(html, "epname")
        api = (f"https://{host}/myseriesapi?{id_type}={final_id}"
               f"&season={season}&epname={epname}&key={key}")
    else:
        api = f"https://{host}/mymovieapi?{id_type}={final_id}&key={key}"
    api_res = fetch(api, referer=embed)
    if api_res.status != 200:
        return "streamhg", [], ("blocked" if api_res.status == 403 else
                                "transport" if api_res.status == 0 else "unverified")
    try:
        files = (json.loads(api_res.text()) or {}).get("data") or []
    except Exception:
        return "streamhg", [], "unverified"
    if not files:
        return "streamhg", [], "no_files"
    candidates = []
    for entry in files[:3]:
        slug = (entry or {}).get("fileslug") or ""
        if not slug:
            continue
        evid = fetch(f"https://pro.iqsmartgames.com/evid/{slug}",
                     referer=embed)
        if evid.status != 200:
            continue
        sid_match = re.search(r'const sid\s*=\s*"([^"]+)"', evid.text())
        if not sid_match:
            continue
        helper = fetch(
            "https://pro.iqsmartgames.com/embedhelper2.php",
            referer=embed, method="POST", data={
                "sid": sid_match.group(1), "UserFavSite": "",
                "currentDomain": json.dumps([host, "pro.iqsmartgames.com"])})
        if helper.status != 200:
            continue
        try:
            payload = json.loads(helper.text()) or {}
            sources = payload.get("sources") or {}
            decoded = json.loads(base64.b64decode(payload.get("mresult") or ""))
        except Exception:
            continue
        for code, source in sources.items():
            site_url = (source or {}).get("siteUrl") or ""
            if "hanerix.com" not in site_url:
                continue
            master_code = decoded.get(code) or ""
            if not master_code:
                continue
            candidates.append({"_hanerix_page": site_url + master_code,
                               "embed": embed})
    if candidates:
        return "streamhg", candidates, None
    return "streamhg", [], "unverified"


def _unwrap_hanerix_page(hanerix_url: str, fetch) -> tuple:
    """hanerix player page -> unpacked hls master candidates."""
    page = fetch(hanerix_url)
    if page.status != 200:
        return [], ("blocked" if page.status == 403 else
                    "transport" if page.status == 0 else "unverified")
    unpacked = unpack_packer(page.text()) or page.text()
    links = extract_hls_links(unpacked)
    candidates = []
    for key in ("hls4", "hls3", "hls2"):
        value = links.get(key) or ""
        if not value:
            continue
        full = value if value.startswith("http") else (
            "https://hanerix.com" + value)
        candidates.append({"url": full, "referer": hanerix_url,
                           "kind_hint": "playlist"})
    if candidates:
        return candidates, None
    return [], "unverified"


def _unwrap_modiplay(saved_url: str, fetch) -> tuple:
    page = fetch(saved_url)
    if page.status != 200:
        return "modiplay", [], ("blocked" if page.status == 403 else
                                "transport" if page.status == 0 else "unverified")
    html = page.text()
    match = re.search(r"/proxy\.php\?p=([a-z0-9]+)(?:&amp;|&)c=([^\"&]+)", html)
    if not match:
        return "modiplay", [], "unverified"
    server, code = match.group(1), match.group(2)
    base = urllib.parse.urlsplit(saved_url)
    origin = f"{base.scheme}://{base.netloc}"
    if server == "streamhg":
        proxy = (f"{origin}/proxy.php?p=streamhg&c={code}"
                 f"&title=x&site_ref=&noredirect=1")
    elif server == "bingr":
        proxy = (f"{origin}/proxy.php?p=bingr&c={code}"
                 f"&title=x&noredirect=1")
    else:
        # The shell lists other servers, but only streamhg/bingr are proven
        # server-side. Anything else is unverified, never dead.
        return "modiplay", [], "unsupported_server"
    player = fetch(proxy, referer=saved_url)
    if player.status != 200:
        return "modiplay", [], ("blocked" if player.status == 403 else
                                "transport" if player.status == 0 else "unverified")
    body = player.text().replace("\\/", "/")
    if server == "streamhg":
        found = [c for c in re.findall(
            r"/stream_proxy\.php\?url=[^\"'<> ]+", body)
            if "master.m3u8" in c]
        if found:
            master = origin + found[0].replace("&amp;", "&")
            return "streamhg", [{"url": master, "referer": saved_url,
                                 "kind_hint": "playlist"}], None
        direct = re.findall(
            r"https?://[A-Za-z0-9.\-]+/[^\s\"'<>]*master\.m3u8", body)
        if direct:
            return "streamhg", [{"url": direct[0].replace("&amp;", "&"),
                                 "referer": proxy,
                                 "kind_hint": "playlist"}], None
        return "streamhg", [], "unverified"
    # bingr -> Vidrift master, Referer MUST be the Vidrift embed domain.
    master = re.search(
        r"https://embed\.vidrift\.net/api/orion/[A-Za-z0-9_\-]+/master\.m3u8",
        body)
    if master:
        return "vidrift", [{"url": master.group(0),
                            "referer": "https://embed.vidrift.net/",
                            "kind_hint": "playlist"}], None
    return "vidrift", [], "shell_unverified"


def _unwrap_vidrift(saved_url: str, fetch) -> tuple:
    referer = "https://embed.vidrift.net/"
    page = fetch(saved_url, referer=referer)
    if page.status != 200:
        return "vidrift", [], ("blocked" if page.status == 403 else
                               "transport" if page.status == 0 else "unverified")
    html = page.text().replace("\\/", "/")
    if '"orionStreams":null' in html:
        return "vidrift", [], "no_streams"
    streams = _extract_json_array(html, "orionStreams")
    if not streams or streams == "unparsed":
        return "vidrift", [], "unverified"
    candidates = []
    for stream in streams:
        url = (stream or {}).get("url") or ""
        if not url:
            continue
        if url.startswith("/"):
            url = "https://embed.vidrift.net" + url
        kind = "playlist" if url.split("?")[0].endswith(".m3u8") else "file"
        candidates.append({"url": url, "referer": referer,
                           "kind_hint": kind})
    if candidates:
        return "vidrift", candidates, None
    return "vidrift", [], "no_streams"


def _unwrap_vidbolt(saved_url: str, fetch) -> tuple:
    page = fetch(saved_url, referer=saved_url)
    if page.status != 200:
        return "vidbolt", [], ("blocked" if page.status == 403 else
                               "transport" if page.status == 0 else "unverified")
    match = re.search(r'var q="([^"]+)"', page.text())
    if not match:
        return "vidbolt", [], "unverified"
    origin = urllib.parse.urlsplit(saved_url)
    resolve_url = f"{origin.scheme}://{origin.netloc}/api/resolve?{match.group(1)}"
    res = fetch(resolve_url, referer=saved_url)
    if res.status != 200:
        return "vidbolt", [], ("blocked" if res.status == 403 else
                               "transport" if res.status == 0 else "unverified")
    try:
        stream = (json.loads(res.text()) or {}).get("stream") or {}
    except Exception:
        return "vidbolt", [], "unverified"
    sources = stream.get("sources") or []
    if not sources and stream.get("url"):
        sources = [stream]
    candidates = []
    for source in sources[:3]:
        url = (source or {}).get("url") or ""
        if url:
            candidates.append({"url": url, "referer": saved_url,
                               "kind_hint": "playlist"})
    if candidates:
        return "vidbolt", candidates, None
    return "vidbolt", [], "unverified"


def _unwrap_vidly(saved_url: str, fetch) -> tuple:
    path = urllib.parse.urlsplit(saved_url).path or ""
    if "/tv/" in path:
        # Series: the signed master 403s on a plain server fetch. Serving
        # it anyway would hand the player a dead token, so stage-1 refuses
        # filmu series from static evidence outright (browser path only).
        return "vidly", [], "series_server_unverified"
    page = fetch(saved_url, referer="https://embed.filmu.in/")
    if page.status != 200:
        return "vidly", [], ("blocked" if page.status == 403 else
                             "transport" if page.status == 0 else "unverified")
    body = page.text().replace("\\/", "/")
    playlists = sorted(set(re.findall(
        r"https://[A-Za-z0-9.\-]+/media/[A-Za-z0-9]+/index\.m3u8", body)))
    candidates = [{"url": url, "referer": "https://vidly.pro/",
                   "kind_hint": "playlist"} for url in playlists[:2]]
    if candidates:
        return "vidly", candidates, None
    return "vidly", [], "unverified"


def _unwrap_vibuxer(saved_url: str, fetch) -> tuple:
    url = clean_url(saved_url)
    page = fetch(url)
    if page.status != 200:
        return "vibuxer", [], ("blocked" if page.status == 403 else
                               "transport" if page.status == 0 else "unverified")
    unpacked = unpack_packer(page.text()) or page.text()
    links = extract_hls_links(unpacked)
    candidates = []
    for key in ("hls4", "hls3", "hls2"):
        value = links.get(key) or ""
        if not value:
            continue
        full = value if value.startswith("http") else urllib.parse.urljoin(url, value)
        candidates.append({"url": full, "referer": url,
                           "kind_hint": "playlist"})
    if candidates:
        return "vibuxer", candidates, None
    return "vibuxer", [], "unverified"


def _unwrap_pixeldrain(saved_url: str, fetch) -> tuple:
    match = re.search(r"/(?:u|d|api/file)/([A-Za-z0-9_-]+)", saved_url)
    if not match:
        return "pixeldrain", [], "unverified"
    direct = f"https://pixeldrain.com/api/file/{match.group(1)}"
    return "pixeldrain", [{"url": direct, "referer": None,
                           "kind_hint": "file"}], None


def _unwrap_fastdl(saved_url: str, fetch) -> tuple:
    page = fetch(saved_url)
    if page.status != 200:
        return "fastdl-beer", [], ("blocked" if page.status == 403 else
                                   "transport" if page.status == 0 else "unverified")
    match = re.search(r'var\s+reurl\s*=\s*["\']([^"\']+)["\']', page.text())
    if not match:
        return "fastdl-beer", [], "unverified"
    raw = match.group(1).strip()
    if "link=" in raw:
        direct = urllib.parse.unquote(raw.split("link=", 1)[1])
    else:
        direct = raw
    if not direct:
        return "fastdl-beer", [], "unverified"
    # Probe ONLY the decoded file address: probing the dl.php page itself
    # returns HTML and proves nothing about the file.
    return "fastdl-beer", [{"url": direct, "referer": None,
                            "kind_hint": "file"}], None


# ── resolve + rank ───────────────────────────────────────────────────────────

def _fail_result(backend: str, failure: str) -> dict:
    return {"ok": False, "backend": backend,
            "group": independence_group(backend), "kind": None, "url": None,
            "mime": None, "size": None, "resumable": False, "renditions": [],
            "failure": failure, "failure_dead": failure == "dead_file",
            "temporary": True}


def resolve_copy(saved_url: str, fetch=default_fetch, probe=None) -> dict:
    """Unwrap one saved link fresh and probe the media it yields.

    Returns a passing copy dict, or a failing dict whose ``failure`` names
    the class (never a guessed URL, never a stale address). A failing copy
    is simply not ranked — only a passing probe can win.
    """
    probe_fn = probe or (lambda u, r, k: probe_media(u, r, k, fetch=fetch))
    backend0 = classify_backend(saved_url)
    if backend0 == "streamhg":
        backend, candidates, failure = _unwrap_iqsmart(saved_url, fetch)
    elif backend0 == "modiplay":
        backend, candidates, failure = _unwrap_modiplay(saved_url, fetch)
    elif backend0 == "vidrift":
        backend, candidates, failure = _unwrap_vidrift(saved_url, fetch)
    elif backend0 == "vidbolt":
        backend, candidates, failure = _unwrap_vidbolt(saved_url, fetch)
    elif backend0 == "vidly":
        backend, candidates, failure = _unwrap_vidly(saved_url, fetch)
    elif backend0 == "vibuxer":
        backend, candidates, failure = _unwrap_vibuxer(saved_url, fetch)
    elif backend0 == "pixeldrain":
        backend, candidates, failure = _unwrap_pixeldrain(saved_url, fetch)
    elif backend0 == "fastdl-beer":
        backend, candidates, failure = _unwrap_fastdl(saved_url, fetch)
    else:
        return _fail_result(backend0, "unknown_backend")
    if failure:
        return _fail_result(backend, failure)
    expanded = []
    for cand in candidates:
        if "_hanerix_page" in cand:
            hanerix_cands, hanerix_failure = _unwrap_hanerix_page(
                cand["_hanerix_page"], fetch)
            if hanerix_failure:
                continue
            expanded.extend(hanerix_cands)
        else:
            expanded.append(cand)
    if not expanded:
        return _fail_result(backend, "unverified")
    last_failure = "unverified"
    for cand in expanded:
        verdict = probe_fn(cand["url"], cand.get("referer"),
                           cand.get("kind_hint", "playlist"))
        if verdict.get("ok"):
            return {"ok": True, "backend": backend,
                    "group": independence_group(backend),
                    "kind": verdict["kind"], "url": cand["url"],
                    "mime": verdict["mime"], "size": verdict["size"],
                    "resumable": bool(verdict["resumable"]),
                    "renditions": verdict["renditions"],
                    "failure": None, "failure_dead": False,
                    "temporary": backend != "pixeldrain"}
        last_failure = verdict.get("failure") or "unverified"
    return _fail_result(backend, last_failure)


def _max_width(copy: dict) -> int:
    widths = [w for w, _h in (copy.get("renditions") or [])]
    return max(widths) if widths else 0


def _watch_order(copy: dict):
    preference = (WATCH_PREFERENCE.index(copy["backend"])
                  if copy["backend"] in WATCH_PREFERENCE else len(WATCH_PREFERENCE))
    has_renditions = 0 if copy.get("renditions") else 1
    return (has_renditions, -_max_width(copy), preference)


def select_watch(copies: list) -> tuple:
    """Winner + up to 2 backups for watch, one per independence group."""
    passing = [c for c in (copies or []) if c.get("ok")]
    ordered = sorted(passing, key=_watch_order)
    chosen, seen = [], set()
    for copy in ordered:
        if copy["group"] in seen:
            continue
        seen.add(copy["group"])
        chosen.append(copy)
        if len(chosen) == 3:
            break
    if not chosen:
        return None, []
    return chosen[0], chosen[1:]


def select_download(copies: list) -> tuple:
    """Winner + up to 2 backups for download: single files only, and only
    the stage-1 download backends (PixelDrain resumable, fastdl.beer not).
    A vidrift direct file is a watch candidate here, not a download winner:
    its download path is still provisional and stays open, not assumed."""
    passing = [c for c in (copies or [])
               if c.get("ok") and c.get("kind") == "file"
               and c.get("backend") in DOWNLOAD_PREFERENCE]
    preference = {name: i for i, name in enumerate(DOWNLOAD_PREFERENCE)}
    ordered = sorted(
        passing,
        key=lambda c: (0 if c.get("resumable") else 1,
                       preference.get(c["backend"], len(preference))))
    chosen, seen = [], set()
    for copy in ordered:
        if copy["group"] in seen:
            continue
        seen.add(copy["group"])
        chosen.append(copy)
        if len(chosen) == 3:
            break
    if not chosen:
        return None, []
    return chosen[0], chosen[1:]


def resolve_release(rows: list, fetch=default_fetch, probe=None,
                    deadline: float | None = None) -> dict:
    """Resolve every copy of one release fresh, then rank watch + download.

    ``rows`` are download_sources-shaped dicts (source_url, final_url,
    service, status, id). Stamped status never ranks: a row is tried on
    its fresh unwrap+probe alone, and only a passing probe can win.
    At most 10 rows are tried, so one release cannot stall a request.
    ``deadline`` is an absolute ``time.monotonic`` value: past it, no
    new sibling is started (Session 101 — the same 10 s budget the
    Stage-2 ladder already had; a sibling started just before the
    deadline still runs to its own probe verdict, as there).

    Siblings resolve in parallel (max 4 workers): ``resolve_copy`` is
    network-only — unwrap + probe, never a DB read or write — so it is
    safe on worker threads, and the write-back happens in the caller.
    The recursive resolver itself is never run in a thread (it shares
    the caller's SQLite connection). One sibling raising must not kill
    the failover: its exception is swallowed and the other copies still
    get their chance. Results are re-sorted into input order before
    ranking, so winners are deterministic. The deadline gates
    *starting* a sibling, not finishing one: a sibling started before
    it runs to its own probe verdict, exactly as the serial ladder did.
    """
    todo = [row for row in list(rows or [])[:10]
            if ((row or {}).get("source_url") or (row or {}).get("final_url"))]
    if not todo:
        return {"copies": [], "failures": [],
                "watch_winner": None, "watch_backups": [],
                "download_winner": None, "download_backups": []}

    def _one(index_row):
        index, row = index_row
        saved = (row or {}).get("source_url") or (row or {}).get("final_url") or ""
        result = resolve_copy(saved, fetch=fetch, probe=probe)
        return index, dict(result, row_id=(row or {}).get("id"))

    outcomes = []
    if len(todo) == 1:
        outcomes.append(_one((0, todo[0])))
    else:
        workers = min(4, len(todo))
        pool = ThreadPoolExecutor(max_workers=workers)
        try:
            pending = {}
            queue = list(enumerate(todo))

            def _submit_next() -> bool:
                if not queue:
                    return False
                if deadline is not None and time.monotonic() > deadline:
                    return False
                item = queue.pop(0)
                pending[pool.submit(_one, item)] = item[0]
                return True

            for _ in range(workers):
                if not _submit_next():
                    break
            while pending:
                done, _not_done = wait(pending, return_when=FIRST_COMPLETED)
                for future in done:
                    del pending[future]
                    try:
                        outcomes.append(future.result())
                    except Exception:
                        continue
                    _submit_next()
        finally:
            # Stragglers finish their own bounded fetches in the
            # background; do not wait for them past the deadline.
            pool.shutdown(wait=False, cancel_futures=True)
    outcomes.sort(key=lambda item: item[0])
    copies, failures = [], []
    for _index, result in outcomes:
        (copies if result.get("ok") else failures).append(result)
    watch_winner, watch_backups = select_watch(copies)
    dl_winner, dl_backups = select_download(copies)
    return {"copies": copies, "failures": failures,
            "watch_winner": watch_winner, "watch_backups": watch_backups,
            "download_winner": dl_winner, "download_backups": dl_backups}
