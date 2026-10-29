#!/usr/bin/env python3
"""Resumable, rate-limited import of MultiMovies catalog and public source links."""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from urllib.robotparser import RobotFileParser

import fast_fetch


DEFAULT_BASE_URL = "https://m1.multimovies.courses"
MAX_RESPONSE_BYTES = 20 * 1024 * 1024
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
ADULT_PATTERNS = (
    r"\b18\+\b", r"\badult\b", r"\berotic\b", r"\bhotshots\b",
    r"\bullu\b", r"\bkooku\b", r"\bprimeplay\b", r"\bnsfw\b",
)
QUALITY_PATTERN = re.compile(
    r"\b(2160p|1440p|1080p|720p|480p|360p|4k|fhd|hd)\b",
    re.IGNORECASE,
)
EPISODE_PATTERN = re.compile(
    r"^(/series/[^/]+)/season/(\d+)/episode/(\d+)/?$",
    re.IGNORECASE,
)


class ImportErrorBase(RuntimeError):
    """Base error for a failed or disallowed import operation."""


class RobotsDenied(ImportErrorBase):
    """Raised when robots.txt disallows a requested public page."""


class FetchError(ImportErrorBase):
    """Raised after retries are exhausted for an HTTP request."""


class _Node:
    def __init__(self, tag: str, attrs: dict[str, str], parent: "_Node | None" = None):
        self.tag = tag
        self.attrs = attrs
        self.parent = parent
        self.parts: list[str | _Node] = []

    def text(self) -> str:
        return "".join(part.text() if isinstance(part, _Node) else part for part in self.parts)


class _TreeParser(HTMLParser):
    VOID_TAGS = {
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    }

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("root", {})
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = _Node(tag.lower(), dict(attrs), self.stack[-1])
        self.stack[-1].parts.append(node)
        if tag.lower() not in self.VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].parts.append(_Node(tag.lower(), dict(attrs), self.stack[-1]))

    def handle_endtag(self, tag):
        tag = tag.lower()
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, data):
        if data:
            self.stack[-1].parts.append(data)


def _walk(node: _Node):
    for part in node.parts:
        if isinstance(part, _Node):
            yield part
            yield from _walk(part)


def _canonical_site_url(base_url: str, url: str) -> str:
    """Keep sitemap entries on the selected site origin, even for stale aliases."""
    base = urllib.parse.urlsplit(base_url)
    parsed = urllib.parse.urlsplit(html.unescape(url.strip()))
    path = parsed.path or "/"
    return urllib.parse.urlunsplit(
        (base.scheme, base.netloc, path, parsed.query, parsed.fragment)
    )


def _locs(xml_text: str) -> list[str]:
    return [
        html.unescape(value).strip()
        for value in re.findall(
            r"<(?:[A-Za-z0-9_-]+:)?loc>(.*?)</(?:[A-Za-z0-9_-]+:)?loc>",
            xml_text,
            re.IGNORECASE | re.DOTALL,
        )
        if value.strip()
    ]


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def series_root_for_episode(url: str) -> tuple[str, int, int] | None:
    parsed = urllib.parse.urlsplit(url)
    match = EPISODE_PATTERN.match(urllib.parse.unquote(parsed.path))
    if not match:
        return None
    root_path, season, episode = match.groups()
    root_url = urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, root_path, "", "")
    )
    return root_url, int(season), int(episode)


def _is_title_url(url: str) -> bool:
    path = urllib.parse.urlsplit(url).path.rstrip("/")
    return bool(re.fullmatch(r"/(?:movie|series)/[^/]+", path, re.IGNORECASE))


def _is_restricted(title: str, slug: str) -> bool:
    value = f"{title} {slug}"
    return any(re.search(pattern, value, re.IGNORECASE) for pattern in ADULT_PATTERNS)


def _page_title(page_html: str, fallback: str) -> str:
    match = re.search(r"<title\b[^>]*>(.*?)</title>", page_html, re.IGNORECASE | re.DOTALL)
    if not match:
        return fallback
    value = re.sub(r"<[^>]+>", " ", match.group(1))
    value = html.unescape(re.sub(r"\s+", " ", value)).strip()
    return value or fallback


def _path_slug(url: str) -> str:
    parts = [part for part in urllib.parse.urlsplit(url).path.split("/") if part]
    return parts[-1] if parts else ""


def _safe_resource_id(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    leaf = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    if leaf:
        return urllib.parse.unquote(leaf)[:200]
    params = urllib.parse.parse_qs(parsed.query)
    for key in ("id", "file", "v"):
        if params.get(key):
            return params[key][0][:200]
    return ""


def _is_temporary_url(url: str) -> int:
    query_keys = {key.lower() for key in urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)}
    return int(bool(query_keys.intersection({"token", "signature", "expires", "expiry", "auth", "policy"})))


def _playback_type(server: dict, url: str) -> str:
    value = str(server.get("type") or "").strip().lower()
    if value in {"iframe", "hls", "mp4", "video", "direct"}:
        return value
    path = urllib.parse.urlsplit(url).path.lower()
    if path.endswith(".m3u8"):
        return "hls"
    if path.endswith((".mp4", ".webm", ".ogg")):
        return "direct"
    return "iframe"


def parse_watch_servers(page_html: str) -> list[dict]:
    match = re.search(r"watchConfig\s*=\s*(\{.*?\});", page_html, re.DOTALL)
    if not match:
        return []
    try:
        config = json.loads(match.group(1))
    except (json.JSONDecodeError, TypeError):
        return []
    servers = config.get("initialServers") or config.get("sources") or []
    return [server for server in servers if isinstance(server, dict)]


def _source_from_server(server: dict, page_url: str, label_suffix: str = "") -> dict | None:
    url = str(server.get("url") or server.get("file") or "").strip()
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    name = str(server.get("name") or server.get("label") or "Server").strip()
    playback_type = _playback_type(server, url)
    label = f"{name} [{playback_type}]"
    if label_suffix:
        label = f"{label} {label_suffix}"
    return {
        "source_name": label,
        "service": re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "multimovies",
        "resource_id": _safe_resource_id(url),
        "source_url": url,
        "final_url": url,
        "playback_type": playback_type,
        "is_temporary": _is_temporary_url(url),
    }


def episode_releases(page_html: str, page_url: str, media: dict, season: int, episode: int) -> list[dict]:
    season_label = f"S{season:02d}"
    episode_label = f"E{episode:02d}"
    releases = []
    for server in parse_watch_servers(page_html):
        source = _source_from_server(server, page_url, f"[{season_label}{episode_label}]")
        if not source:
            continue
        server_name = str(server.get("name") or server.get("label") or "Server").strip()
        releases.append({
            "release_title": f"{media['clean_title']} {season_label}{episode_label} {server_name}",
            "quality": str(server.get("quality") or "HD"),
            "codec": "",
            "size": "",
            "languages": media.get("language"),
            "season": season_label,
            "episode": episode_label,
            "intermediate_url": source["source_url"],
            "source_site": "multimovies",
            "sources": [source],
        })
    return releases


def download_page_urls(page_url: str, page_html: str, base_host: str) -> list[str]:
    parser = _TreeParser()
    parser.feed(page_html)
    result = []
    for node in _walk(parser.root):
        if node.tag != "a":
            continue
        href = node.attrs.get("href", "").strip()
        if not href:
            continue
        absolute = urllib.parse.urljoin(page_url, href)
        parsed = urllib.parse.urlsplit(absolute)
        if (
            parsed.scheme in {"http", "https"}
            and parsed.hostname == base_host
            and parsed.path.startswith("/download/")
        ):
            result.append(absolute)
    return _unique(result)


def _quality_for_node(node: _Node) -> str:
    current = node
    for _ in range(8):
        if current is None:
            break
        matches = {value.lower() for value in QUALITY_PATTERN.findall(current.text())}
        if len(matches) == 1:
            return next(iter(matches)).upper()
        current = current.parent
    return "Download"


def parse_download_mirrors(
    download_html: str,
    download_page_url: str,
    base_host: str,
    media: dict,
    season: int | None = None,
    episode: int | None = None,
) -> list[dict]:
    parser = _TreeParser()
    parser.feed(download_html)
    groups: dict[str, list[dict]] = {}
    seen_urls: set[str] = set()
    season_label = f"S{season:02d}" if season is not None else None
    episode_label = f"E{episode:02d}" if episode is not None else None
    for node in _walk(parser.root):
        if node.tag != "a":
            continue
        classes = set(node.attrs.get("class", "").lower().split())
        if "dl-mirror-btn" not in classes:
            continue
        href = urllib.parse.urljoin(download_page_url, node.attrs.get("href", "").strip())
        parsed = urllib.parse.urlsplit(href)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.hostname == base_host:
            continue
        if href in seen_urls:
            continue
        seen_urls.add(href)
        label = re.sub(r"\s+", " ", node.text()).strip()
        label = html.unescape(label or node.attrs.get("title", "") or parsed.hostname)
        quality = _quality_for_node(node)
        source = {
            "source_name": label[:240],
            "service": re.sub(r"[^a-z0-9]+", "-", parsed.hostname.lower()).strip("-"),
            "resource_id": _safe_resource_id(href),
            "source_url": href,
            "final_url": href,
            "playback_type": "download",
            "is_temporary": _is_temporary_url(href),
        }
        groups.setdefault(quality, []).append(source)

    releases = []
    year = media.get("year")
    for quality, sources in sorted(groups.items()):
        suffix = f" {season_label}{episode_label}" if season_label and episode_label else ""
        releases.append({
            "release_title": f"{media['clean_title']} {year or ''} {quality} Download{suffix}".strip(),
            "quality": quality,
            "codec": "",
            "size": "",
            "languages": media.get("language"),
            "season": season_label,
            "episode": episode_label,
            "intermediate_url": download_page_url,
            "source_site": "multimovies",
            "sources": sources,
        })
    return releases


class SiteClient:
    def __init__(self, base_url: str, request_interval: float, retries: int = 3):
        parsed = urllib.parse.urlsplit(base_url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("The base URL must be an absolute HTTPS URL.")
        self.base_url = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "", "", "")).rstrip("/")
        self.host = parsed.hostname.lower()
        self.request_interval = max(0.0, request_interval)
        self.retries = max(1, retries)
        self.robot_parser: RobotFileParser | None = None
        self._next_request_at = 0.0

    def _wait(self):
        now = time.monotonic()
        if now < self._next_request_at:
            time.sleep(self._next_request_at - now)
        self._next_request_at = time.monotonic() + self.request_interval

    def get_text(self, url: str, *, check_robots: bool = True) -> tuple[int, str, str]:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname != self.host:
            raise ValueError("Refusing a non-HTTPS or cross-host request.")
        if check_robots and self.robot_parser and not self.robot_parser.can_fetch(fast_fetch.USER_AGENT, url):
            raise RobotsDenied(f"robots.txt disallows {parsed.path}")

        for attempt in range(self.retries):
            self._wait()
            request = urllib.request.Request(url, headers={
                "User-Agent": fast_fetch.USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            })
            try:
                with urllib.request.urlopen(request, timeout=20) as response:
                    final_url = response.geturl()
                    final = urllib.parse.urlsplit(final_url)
                    if final.hostname != self.host:
                        raise ValueError("Refusing a redirect to another host.")
                    raw = response.read(MAX_RESPONSE_BYTES + 1)
                    if len(raw) > MAX_RESPONSE_BYTES:
                        raise FetchError("Response exceeded the configured text size limit.")
                    charset = response.headers.get_content_charset() or "utf-8"
                    return response.status, final_url, raw.decode(charset, "replace")
            except urllib.error.HTTPError as error:
                if error.code in RETRYABLE_STATUSES and attempt + 1 < self.retries:
                    retry_after = error.headers.get("Retry-After", "") if error.headers else ""
                    delay = int(retry_after) if retry_after.isdigit() else 2 ** attempt
                    time.sleep(min(max(delay, 1), 60))
                    continue
                body = error.read(MAX_RESPONSE_BYTES).decode("utf-8", "replace")
                return error.code, error.geturl(), body
            except (urllib.error.URLError, TimeoutError, OSError) as error:
                if attempt + 1 >= self.retries:
                    raise FetchError(f"Request failed ({type(error).__name__}).") from None
                time.sleep(min(2 ** attempt, 30))
        raise FetchError("Request retries exhausted.")

    def load_robots(self):
        robots_url = self.base_url + "/robots.txt"
        status, final_url, body = self.get_text(robots_url, check_robots=False)
        if status != 200 or urllib.parse.urlsplit(final_url).hostname != self.host:
            raise FetchError(f"Could not read robots.txt (HTTP {status}).")
        parser = RobotFileParser(final_url)
        parser.parse(body.splitlines())
        delay = parser.crawl_delay(fast_fetch.USER_AGENT) or parser.crawl_delay("*") or 0
        if delay:
            self.request_interval = max(self.request_interval, float(delay))
        self.robot_parser = parser


def fetch_sitemap_inventory(client: SiteClient) -> tuple[list[str], list[str]]:
    status, _, index_xml = client.get_text(client.base_url + "/sitemap.xml")
    if status != 200:
        raise FetchError(f"MultiMovies sitemap index returned HTTP {status}.")
    child_maps = _locs(index_xml)
    if not child_maps:
        raise FetchError("MultiMovies sitemap index contained no child sitemaps.")

    title_urls: list[str] = []
    episode_urls: list[str] = []
    title_maps = 0
    episode_maps = 0
    for child in child_maps:
        path = urllib.parse.urlsplit(child).path.rsplit("/", 1)[-1].lower()
        if not re.fullmatch(r"sitemap-(?:titles|episodes)-\d+\.xml", path):
            continue
        kind = "title" if path.startswith("sitemap-titles-") else "episode"
        map_url = _canonical_site_url(client.base_url, child)
        code, _, xml_text = client.get_text(map_url)
        if code != 200:
            raise FetchError(f"{path} returned HTTP {code}.")
        urls = [_canonical_site_url(client.base_url, loc) for loc in _locs(xml_text)]
        if kind == "title":
            title_maps += 1
            title_urls.extend(url for url in urls if _is_title_url(url))
        else:
            episode_maps += 1
            episode_urls.extend(url for url in urls if series_root_for_episode(url))

    title_urls = _unique(title_urls)
    episode_urls = _unique(episode_urls)
    if title_maps == 0 or not title_urls:
        raise FetchError("No MultiMovies title sitemap pages were discovered.")
    if episode_maps == 0:
        print("Warning: no episode sitemaps were listed; importing title pages only.", flush=True)
    print(
        f"Sitemaps: {title_maps} title maps / {len(title_urls)} title pages; "
        f"{episode_maps} episode maps / {len(episode_urls)} episode pages.",
        flush=True,
    )
    return title_urls, episode_urls


def discover_sitemaps(client: SiteClient) -> tuple[list[str], list[str], dict[str, list[str]]]:
    """Discover title and episode URLs from sitemaps, grouped by series root."""
    title_urls, episode_urls = fetch_sitemap_inventory(client)
    episodes_by_root: dict[str, list[str]] = {}
    for episode_url in episode_urls:
        info = series_root_for_episode(episode_url)
        if info:
            episodes_by_root.setdefault(info[0], []).append(episode_url)
    for root, urls in episodes_by_root.items():
        urls.sort(key=lambda url: (
            series_root_for_episode(url)[1],
            series_root_for_episode(url)[2],
        ))
    return title_urls, episode_urls, episodes_by_root


def _source_record(url: str, page_html: str) -> tuple[str, str, str]:
    title = _page_title(page_html, _path_slug(url))
    info = series_root_for_episode(url)
    if info:
        slug = f"{_path_slug(info[0])}-s{info[1]:02d}e{info[2]:02d}"
    else:
        slug = _path_slug(url)
    return url, title, slug


def _cache_urls(urls: list[str]):
    records = [
        (url, None, _path_slug(url), "multimovies")
        for url in _unique(urls)
    ]
    with fast_fetch._DB_WRITE_LOCK:
        with fast_fetch.get_db() as conn:
            for start in range(0, len(records), 2000):
                chunk = records[start:start + 2000]
                conn.executemany(
                    """
                    INSERT INTO sitemap_cache (loc, lastmod, slug, scraped, site)
                    VALUES (?, ?, ?, 0, ?)
                    ON CONFLICT(loc) DO UPDATE SET
                        slug = excluded.slug,
                        site = excluded.site,
                        lastmod = COALESCE(excluded.lastmod, sitemap_cache.lastmod)
                    """,
                    chunk,
                )


def _cache_status() -> dict[str, int]:
    with fast_fetch.get_db() as conn:
        return {
            row["loc"]: int(row["scraped"] or 0)
            for row in conn.execute(
                "SELECT loc, scraped FROM sitemap_cache WHERE site = 'multimovies'"
            )
        }


def _mark_cache(urls: list[str], status: int):
    with fast_fetch._DB_WRITE_LOCK:
        with fast_fetch.get_db() as conn:
            conn.executemany(
                "UPDATE sitemap_cache SET scraped = ? WHERE loc = ? AND site = 'multimovies'",
                [(status, url) for url in _unique(urls)],
            )


def _add_source_pages(post_id: int, records: list[tuple[str, str, str]]):
    with fast_fetch._DB_WRITE_LOCK:
        with fast_fetch.get_db() as conn:
            for url, title, slug in records:
                cursor = conn.execute(
                    """
                    INSERT INTO post_sources (post_id, source_site, url, source_title, source_slug)
                    VALUES (?, 'multimovies', ?, ?, ?)
                    ON CONFLICT(source_site, url) DO UPDATE SET
                        source_title = COALESCE(excluded.source_title, post_sources.source_title),
                        source_slug = COALESCE(excluded.source_slug, post_sources.source_slug),
                        last_seen_at = CURRENT_TIMESTAMP
                    WHERE post_sources.post_id = excluded.post_id
                    """,
                    (post_id, url, title or None, slug or None),
                )
                if cursor.rowcount == 0:
                    raise ValueError("An episode page is already linked to another media record.")


def _fetch_page(client: SiteClient, url: str) -> tuple[str, str]:
    status, final_url, page_html = client.get_text(url)
    if status != 200:
        path = urllib.parse.urlsplit(url).path
        raise FetchError(f"HTTP {status} for {path}.")
    return final_url, page_html


def _add_download_releases(
    client: SiteClient,
    page_url: str,
    page_html: str,
    media: dict,
    base_host: str,
    season: int | None = None,
    episode: int | None = None,
) -> tuple[list[dict], list[str]]:
    releases = []
    download_pages = download_page_urls(page_url, page_html, base_host)
    for download_page in download_pages:
        _, download_html = _fetch_page(client, download_page)
        releases.extend(parse_download_mirrors(
            download_html,
            download_page,
            base_host,
            media,
            season=season,
            episode=episode,
        ))
    return releases, download_pages


def _save_media(data: dict, page_records: list[tuple[str, str, str]], cache_urls: list[str]):
    post_id = fast_fetch.save_scraped_data(
        data,
        enrich_metadata=False,
        ensure_db=False,
    )
    _add_source_pages(post_id, page_records)
    _mark_cache(cache_urls, 1)
    return post_id


def _process_movie(client: SiteClient, page_url: str, base_host: str, dry_run: bool) -> dict:
    final_url, page_html = _fetch_page(client, page_url)
    data = fast_fetch.extract_post_data_multimovies(
        final_url,
        page_html,
        verbose=False,
        crawl_episodes=False,
        resolve_streams=False,
    )
    if not data:
        raise FetchError("The movie page did not produce a catalog record.")
    if _is_restricted(data.get("title", ""), data.get("slug", "")):
        data["is_18_plus"] = 1

    extra_releases, download_pages = _add_download_releases(
        client, final_url, page_html, data, base_host,
    )
    data["releases"].extend(extra_releases)
    records = [_source_record(final_url, page_html)]
    if final_url != page_url:
        records.append(_source_record(page_url, page_html))
    if dry_run:
        return {
            "restricted": False,
            "releases": len(data["releases"]),
            "sources": sum(len(release.get("sources", [])) for release in data["releases"]),
            "pages": 1 + len(download_pages),
            "title": data["clean_title"],
        }
    _save_media(data, records, [page_url])
    return {
        "restricted": False,
        "releases": len(data["releases"]),
        "sources": sum(len(release.get("sources", [])) for release in data["releases"]),
        "pages": 1 + len(download_pages),
        "title": data["clean_title"],
    }


def _process_series(
    client: SiteClient,
    root_url: str,
    episode_urls: list[str],
    base_host: str,
    dry_run: bool,
    episode_limit: int | None = None,
) -> dict:
    final_root, root_html = _fetch_page(client, root_url)
    data = fast_fetch.extract_post_data_multimovies(
        final_root,
        root_html,
        verbose=False,
        crawl_episodes=False,
        resolve_streams=False,
    )
    if not data:
        raise FetchError("The series page did not produce a catalog record.")
    if _is_restricted(data.get("title", ""), data.get("slug", "")):
        data["is_18_plus"] = 1

    base_releases = list(data.get("releases") or [])
    source_records = [_source_record(final_root, root_html)]
    if final_root != root_url:
        source_records.append(_source_record(root_url, root_html))
    completed_episode_urls = []
    restricted_episode_urls = []
    download_pages_seen = set()
    selected_episodes = episode_urls[:episode_limit] if episode_limit is not None else episode_urls
    failures = []

    for episode_url in selected_episodes:
        episode_info = series_root_for_episode(episode_url)
        if not episode_info:
            failures.append(episode_url)
            continue
        _, season, episode = episode_info
        try:
            episode_final, episode_html = _fetch_page(client, episode_url)
            episode_title = _page_title(episode_html, _path_slug(episode_url))
            if _is_restricted(episode_title, _path_slug(episode_url)):
                restricted_episode_urls.append(episode_url)
                continue
            base_releases.extend(
                episode_releases(episode_html, episode_final, data, season, episode)
            )
            extra_releases, download_pages = _add_download_releases(
                client,
                episode_final,
                episode_html,
                data,
                base_host,
                season=season,
                episode=episode,
            )
            base_releases.extend(extra_releases)
            download_pages_seen.update(download_pages)
            source_records.append(_source_record(episode_final, episode_html))
            if episode_final != episode_url:
                source_records.append(_source_record(episode_url, episode_html))
            completed_episode_urls.append(episode_url)
        except (FetchError, RobotsDenied, ValueError) as error:
            failures.append(episode_url)
            print(
                f"  Episode failed ({_path_slug(episode_url)}): {type(error).__name__}",
                flush=True,
            )

    if failures and not dry_run:
        _mark_cache(restricted_episode_urls, -1)
        return {
            "failed": len(failures),
            "releases": 0,
            "sources": 0,
            "pages": 1 + len(completed_episode_urls),
        }

    data["releases"] = base_releases
    if dry_run:
        return {
            "restricted": False,
            "releases": len(base_releases),
            "sources": sum(len(release.get("sources", [])) for release in base_releases),
            "pages": 1 + len(completed_episode_urls) + len(download_pages_seen),
            "episodes": len(completed_episode_urls),
            "title": data["clean_title"],
        }

    post_id = fast_fetch.save_scraped_data(
        data,
        enrich_metadata=False,
        ensure_db=False,
    )
    _add_source_pages(post_id, source_records)
    _mark_cache([root_url, *completed_episode_urls], 1)
    _mark_cache(restricted_episode_urls, -1)
    return {
        "restricted": False,
        "releases": len(base_releases),
        "sources": sum(len(release.get("sources", [])) for release in base_releases),
        "pages": 1 + len(completed_episode_urls) + len(download_pages_seen),
        "episodes": len(completed_episode_urls),
        "title": data["clean_title"],
    }


def run_import(args: argparse.Namespace) -> int:
    client = SiteClient(args.base_url, args.request_interval)
    client.load_robots()
    title_urls, episode_urls, episodes_by_root = discover_sitemaps(client)

    roots = _unique(title_urls + list(episodes_by_root))
    if args.only_root:
        requested = [_canonical_site_url(client.base_url, url) for url in args.only_root]
        missing = [url for url in requested if url not in roots]
        if missing:
            raise ValueError("A requested root URL was not present in the current sitemaps.")
        roots = requested
    if args.limit_roots is not None:
        roots = roots[:max(0, args.limit_roots)]

    all_urls = _unique(title_urls + episode_urls + list(episodes_by_root))
    if not args.dry_run:
        default_db = (
            Path("/home/ubuntu/radd-stream-data/multimovies.db")
            if Path("/home/ubuntu/radd-stream-data").exists()
            else fast_fetch.BASE_DIR / "multimovies.db"
        )
        db_target = args.db_path or os.environ.get("RADD_MULTIMOVIES_DB") or str(default_db)
        fast_fetch.DB_PATH = Path(db_target)
        fast_fetch.init_db()
        print(f"Targeting dedicated database: {fast_fetch.DB_PATH}", flush=True)
        _cache_urls(all_urls)
        status = _cache_status()
    else:
        status = {}

    counters = {
        "completed": 0,
        "skipped": 0,
        "restricted": 0,
        "failed": 0,
        "pages": 0,
        "releases": 0,
        "sources": 0,
        "episodes": 0,
    }
    for index, root_url in enumerate(roots, 1):
        episode_list = episodes_by_root.get(root_url, [])
        if not args.dry_run and not args.refresh:
            all_done = status.get(root_url) in (1, -1) and all(
                status.get(url) in (1, -1) for url in episode_list
            )
            if all_done:
                counters["skipped"] += 1
                continue
        try:
            path = urllib.parse.urlsplit(root_url).path
            if path.startswith("/movie/"):
                result = _process_movie(client, root_url, client.host, args.dry_run)
            elif path.startswith("/series/"):
                result = _process_series(
                    client,
                    root_url,
                    episode_list,
                    client.host,
                    args.dry_run,
                    episode_limit=args.limit_episodes if args.dry_run else None,
                )
            else:
                counters["failed"] += 1
                print(f"[{index}/{len(roots)}] Unsupported page path; skipped.", flush=True)
                continue

            if result.get("failed"):
                counters["failed"] += result["failed"]
            elif result.get("restricted"):
                counters["restricted"] += 1
                counters["completed"] += 1
            else:
                counters["completed"] += 1
                counters["pages"] += result.get("pages", 0)
                counters["releases"] += result.get("releases", 0)
                counters["sources"] += result.get("sources", 0)
                counters["episodes"] += result.get("episodes", 0)

            if index % args.progress_every == 0 or index == len(roots):
                print(
                    f"[{index}/{len(roots)}] complete={counters['completed']} "
                    f"skipped={counters['skipped']} restricted={counters['restricted']} "
                    f"failed={counters['failed']} releases={counters['releases']} "
                    f"sources={counters['sources']}",
                    flush=True,
                )
        except (FetchError, RobotsDenied, ValueError, json.JSONDecodeError) as error:
            counters["failed"] += 1
            print(
                f"[{index}/{len(roots)}] Failed {_path_slug(root_url)}: {type(error).__name__}",
                flush=True,
            )

    mode = "Dry run" if args.dry_run else "Import"
    print(
        f"{mode} summary: roots={len(roots)} completed={counters['completed']} "
        f"skipped={counters['skipped']} restricted={counters['restricted']} "
        f"failed={counters['failed']} pages={counters['pages']} "
        f"episodes={counters['episodes']} releases={counters['releases']} "
        f"sources={counters['sources']}",
        flush=True,
    )
    if args.dry_run and args.limit_episodes is not None:
        print("Dry-run episode limit was applied; this run did not import partial series.", flush=True)
    return 1 if counters["failed"] else 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import MultiMovies title pages, episode servers, and download mirrors."
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Current MultiMovies origin.")
    parser.add_argument(
        "--request-interval",
        type=float,
        default=0.5,
        help="Minimum seconds between requests; defaults to two requests per second.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Fetch and parse without writing to SQLite.")
    parser.add_argument("--refresh", action="store_true", help="Reprocess URLs already marked complete.")
    parser.add_argument("--limit-roots", type=int, default=None, help="Limit the number of movie/series roots.")
    parser.add_argument(
        "--limit-episodes",
        type=int,
        default=None,
        help="Dry-run only: limit episodes per series root; never used for a production import.",
    )
    parser.add_argument(
        "--only-root",
        action="append",
        default=[],
        help="Process one sitemap title URL; may be supplied more than once.",
    )
    parser.add_argument(
        "--db-path",
        default=None,
        help="Path to dedicated SQLite database (defaults to Fast_Fetch/multimovies.db).",
    )
    parser.add_argument("--progress-every", type=int, default=25, help="Print progress after this many roots.")
    args = parser.parse_args(argv)
    if args.limit_episodes is not None and not args.dry_run:
        parser.error("--limit-episodes is allowed only with --dry-run.")
    if args.progress_every < 1:
        parser.error("--progress-every must be at least 1.")
    return args


if __name__ == "__main__":
    try:
        raise SystemExit(run_import(parse_args()))
    except KeyboardInterrupt:
        print("Import interrupted; completed media groups remain saved and the rest can be resumed.", flush=True)
        raise SystemExit(130)
