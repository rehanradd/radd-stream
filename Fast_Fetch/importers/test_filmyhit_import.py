#!/usr/bin/env python3
"""
test_filmyhit_import.py — offline unit tests for the FilmyHit staging importer.

No test touches the network: the socket is replaced with a raiser for the whole
module, and every fixture is shaped from pages measured on 2026-10-29. The rules
kept here:

* only `*-free-download` detail URLs from the sitemap are queued;
* the `@graph` Movie/TVSeries node supplies metadata, and a page without one is
  parked rather than invented;
* a release is an `/all-format-downloads-...` anchor with its own quality, size
  and container; its `/d/.../server-N` endpoints are stored **unverified** and
  unfollowed — one sampled endpoint was a JS "Verify to Continue" interstitial
  and two were Cloudflare 502;
* series are season packs on this site, so no episode split is invented.
"""

from __future__ import annotations

import contextlib
import io
import json
import socket
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import import_filmyhit as fh  # noqa: E402


class _NoLiveSocket:
    def __init__(self, *args, **kwargs):
        raise AssertionError("offline suite attempted a live connection")


socket.socket = _NoLiveSocket  # type: ignore[attr-defined]


@contextlib.contextmanager
def silenced():
    buf = io.StringIO()
    with contextlib.ExitStack() as stack:
        for stream in ("stdout", "stderr"):
            stack.enter_context(mock.patch.object(sys, stream, buf))
        yield buf


MOVIE_SLUG = "weapons-2025-hindi-dubbed-movie-free-download"
MOVIE_URL = f"https://filmyhit.mobile/{MOVIE_SLUG}"
SERIES_SLUG = "tyson-2026-s01-hindi-dubbed-series-free-download"
SERIES_URL = f"https://filmyhit.mobile/{SERIES_SLUG}"
POSTER = "https://filmyhit.mobile/uploads/posters/22393.jpg?v=1"
BRIDGE_1 = "/all-format-downloads-weapons-2025-480-full-hd-1"
BRIDGE_2 = "/all-format-downloads-weapons-2025-720-full-hd-2"
BRIDGE_3 = "/all-format-downloads-weapons-2025-1080-full-hd-3"

SITEMAP = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://filmyhit.mobile/</loc></url>
  <url><loc>https://filmyhit.mobile/?page=2</loc></url>
  <url><loc>https://filmyhit.mobile/cat/bollywood</loc></url>
  <url><loc>{MOVIE_URL}</loc><lastmod>2026-10-27</lastmod></url>
  <url><loc>{MOVIE_URL}</loc><lastmod>2026-10-27</lastmod></url>
  <url><loc>{SERIES_URL}</loc></url>
  <url><loc>https://filmyhit.mobile/search.php</loc></url>
</urlset>"""


def ld_node(**overrides) -> dict:
    node = {
        "@type": "Movie",
        "@id": MOVIE_URL + "#movie",
        "url": MOVIE_URL,
        "name": "Weapons (2025) Hindi Dubbed Movie",
        "description": "When all but one child from the same class vanish.",
        "image": [POSTER],
        "dateCreated": "2025",
        "datePublished": "2025-08-08",
        "duration": "PT2H8M",
        "inLanguage": "Hindi dubbed",
        "sameAs": "https://www.imdb.com/title/tt26581740/",
        "genre": ["Horror", "Mystery"],
        "actor": [{"@type": "Person", "name": "Julia Garner"},
                  {"@type": "Person", "name": "Josh Brolin"}],
    }
    node.update(overrides)
    return node


def page(node: dict | None = ld_node(), links: list[str] | None = None,
         title: str = "Weapons (2025) Hindi Dubbed Movie") -> str:
    graph = {
        "@context": "https://schema.org",
        "@graph": [
            {"@type": "Organization", "name": "Filmyhit.mobile"},
            {"@type": "WebSite", "name": "Filmyhit.mobile"},
            {"@type": "WebPage", "name": title},
        ],
    }
    if node is not None:
        graph["@graph"].append(node)
    anchors = "".join(
        f'<a href="{link[0]}">{link[1]}</a>' for link in (links or []))
    return ("<html><head>"
            f'<script type="application/ld+json">{json.dumps(graph)}</script>'
            f"</head><body>{anchors}</body></html>")


MOVIE_LINKS = [
    (BRIDGE_1, "480p522.26 MB · MKV"),
    (BRIDGE_2, "720p1.21 GB · MKV"),
    (BRIDGE_3, "1080p2.88 GB · MKV"),
    (BRIDGE_1, ""),
    ("https://brightadnetwork.com/jump/next.php?r=12324922", "Download ↓"),
]


def bridge(servers: int = 2, prefix: str = "server-") -> str:
    return "".join(
        f'<a href="/d/movie-1/file-1/{prefix}{n}">Start Download - Server {n}</a>'
        for n in range(1, servers + 1))


class SitemapTests(unittest.TestCase):
    def test_only_detail_urls_and_deduped(self):
        rows = fh.parse_sitemap(SITEMAP)
        self.assertEqual([loc for loc, _ in rows], [MOVIE_URL, SERIES_URL])

    def test_lastmod_is_kept(self):
        rows = dict(fh.parse_sitemap(SITEMAP))
        self.assertEqual(rows[MOVIE_URL], "2026-10-27")
        self.assertIsNone(rows[SERIES_URL])

    def test_slug_validation(self):
        self.assertEqual(fh.slug_from(MOVIE_URL), MOVIE_SLUG)
        self.assertEqual(fh.slug_from("https://filmyhit.mobile/cat/bollywood"), "")
        self.assertEqual(fh.slug_from("https://filmyhit.mobile/?page=2"), "")


class FieldTests(unittest.TestCase):
    def test_clean_title_strips_site_label(self):
        self.assertEqual(fh.clean_title("Weapons (2025) Hindi Dubbed Movie"),
                         "Weapons (2025) Hindi Dubbed")
        self.assertEqual(fh.clean_title("Tyson (2026) S01 Hindi Dubbed Series"),
                         "Tyson (2026) S01 Hindi Dubbed")

    def test_iso_duration(self):
        self.assertEqual(fh.iso_duration_text("PT2H8M"), "02:08:00")
        self.assertEqual(fh.iso_duration_text("PT45M"), "00:45:00")
        self.assertIsNone(fh.iso_duration_text("2h8m"))

    def test_sizes(self):
        self.assertEqual(fh.size_bytes("522.26 MB"), int(522.26 * 1024 ** 2))
        self.assertEqual(fh.size_bytes("1.21 GB"), int(1.21 * 1024 ** 3))
        self.assertIsNone(fh.size_bytes("no size"))

    def test_quality_and_season(self):
        self.assertEqual(fh.quality_of("1080p2.11 GB · MKV"), "1080p")
        self.assertEqual(fh.quality_of("4K 8 GB"), "2160p")
        self.assertEqual(fh.season_of("Tyson (2026) S01 Hindi Dubbed"), 1)
        self.assertEqual(fh.season_of("Show Season 3"), 3)

    def test_languages(self):
        self.assertEqual(fh.languages_for("Hindi dubbed"), ["Hindi"])
        self.assertEqual(fh.languages_for(["Hindi", "English"]), ["Hindi", "English"])


class JsonLdTests(unittest.TestCase):
    def test_graph_movie_node_is_picked(self):
        node = fh.parse_jsonld(page())
        self.assertEqual(node["@type"], "Movie")
        self.assertEqual(node["name"], "Weapons (2025) Hindi Dubbed Movie")

    def test_no_node_returns_none(self):
        self.assertIsNone(fh.parse_jsonld(page(None)))

    def test_organization_only_graph_returns_none(self):
        html = ('<script type="application/ld+json">'
                + json.dumps({"@graph": [{"@type": "Organization"}]})
                + "</script>")
        self.assertIsNone(fh.parse_jsonld(html))


class ReleaseTests(unittest.TestCase):
    def test_anchors_become_releases_without_ads(self):
        releases = fh.releases_from_page(page(links=MOVIE_LINKS), MOVIE_URL,
                                         "Weapons", None)
        self.assertEqual(len(releases), 3)
        self.assertEqual([r["quality"] for r in releases],
                         ["480p", "720p", "1080p"])
        self.assertEqual(releases[0]["codec"], "MKV")
        self.assertEqual(releases[1]["size_bytes"], int(1.21 * 1024 ** 3))
        self.assertTrue(all(r["bridge_url"].startswith(fh.BASE_URL) for r in releases))
        self.assertEqual(releases[0]["sources"], [])

    def test_series_release_carries_the_season(self):
        links = [(BRIDGE_1, "480p884.90 MB · MKV")]
        releases = fh.releases_from_page(page(links=links), SERIES_URL,
                                         "Tyson (2026) S01 Hindi Dubbed", 1)
        self.assertEqual(releases[0]["season_number"], 1)
        self.assertIsNone(releases[0]["episode_number"])
        self.assertEqual(releases[0]["label"], "Tyson (2026) S01 Hindi Dubbed [480p]")

    def test_server_sources_are_unverified_and_unfollowed(self):
        sources = fh.server_sources(bridge(3), "1080p")
        self.assertEqual(len(sources), 3)
        for src in sources:
            self.assertEqual(src["status"], "unverified")
            self.assertIsNone(src["final_url"])
            self.assertEqual(src["playback_type"], "download")
            self.assertEqual(src["is_temporary"], 0)
            self.assertEqual(src["quality"], "1080p")
            self.assertEqual(src["service"], "filmyhit-server")
            self.assertTrue(src["source_url"].startswith(fh.BASE_URL + "/d/"))

    def test_server_sources_dedupe(self):
        html = bridge(2) + bridge(2)
        self.assertEqual(len(fh.server_sources(html, "720p")), 2)

    def test_foreign_links_are_not_servers(self):
        html = '<a href="https://brightadnetwork.com/jump/next.php?r=1">Download</a>'
        self.assertEqual(fh.server_sources(html, "480p"), [])


class BuildRecordTests(unittest.TestCase):
    def test_movie_record_fields(self):
        record = fh.build_record(MOVIE_URL, page(links=MOVIE_LINKS))
        self.assertEqual(record["canonical_key"], MOVIE_SLUG)
        self.assertEqual(record["title"], "Weapons (2025) Hindi Dubbed")
        self.assertEqual(record["media_type"], "movie")
        self.assertEqual(record["year"], 2025)
        self.assertEqual(record["duration"], "02:08:00")
        self.assertEqual(record["imdb_id"], "tt26581740")
        self.assertEqual(record["poster_url"], POSTER)
        self.assertEqual(json.loads(record["languages"]), ["Hindi"])
        self.assertEqual(len(record["releases"]), 3)
        self.assertIsNone(record["seasons"])

    def test_series_record(self):
        node = ld_node(name="Tyson (2026) S01 Hindi Dubbed Series",
                       url=SERIES_URL, dateCreated="2026",
                       sameAs=None, duration=None)
        record = fh.build_record(SERIES_URL, page(node, links=[
            ("/all-format-downloads-tyson-2026-s01-480-full-hd-9",
             "480p884.90 MB · MKV")]))
        self.assertEqual(record["media_type"], "series")
        self.assertEqual(json.loads(record["seasons"]), [1])
        self.assertEqual(record["releases"][0]["season_number"], 1)

    def test_no_jsonld_returns_none(self):
        self.assertIsNone(fh.build_record(MOVIE_URL, page(None)))

    def test_adult_and_animated_flags(self):
        adult = fh.build_record(MOVIE_URL, page(ld_node(
            name="Stepmom F-cked Movie")))
        self.assertEqual(adult["is_18_plus"], 1)
        cartoon = fh.build_record(MOVIE_URL, page(ld_node(
            name="Toon (2024) Hindi Dubbed Movie", genre=["Animation"])))
        self.assertEqual(cartoon["is_animated"], 1)
        self.assertEqual(cartoon["is_18_plus"], 0)

    def test_annotate_sources_attaches_servers_and_errors(self):
        record = fh.build_record(MOVIE_URL, page(links=MOVIE_LINKS))
        bridge_url = record["releases"][0]["bridge_url"]
        fh.annotate_sources(record, {bridge_url: bridge(4)},
                            {record["releases"][1]["bridge_url"]: "http-502"})
        self.assertEqual(len(record["releases"][0]["sources"]), 4)
        self.assertEqual(record["releases"][1]["sources"], [])
        self.assertEqual(record["releases"][1]["raw_meta"]["bridge_error"], "http-502")


class StagingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db = Path(self.tmp.name)

    def tearDown(self):
        self.db.unlink(missing_ok=True)

    def record(self):
        record = fh.build_record(MOVIE_URL, page(links=MOVIE_LINKS))
        fh.annotate_sources(record, {
            record["releases"][0]["bridge_url"]: bridge(3),
            record["releases"][1]["bridge_url"]: bridge(2),
            record["releases"][2]["bridge_url"]: bridge(1),
        }, {})
        return record

    def test_export_writes_rows_and_marks_cache(self):
        result = fh.export_staging(self.db, [self.record()])
        self.assertEqual(result["posts_written"], 1)
        self.assertEqual(result["releases_written"], 3)
        self.assertEqual(result["sources_written"], 6)
        conn = sqlite3.connect(self.db)
        try:
            self.assertEqual(conn.execute(
                "SELECT COUNT(*) FROM sources WHERE status = 'active'").fetchone()[0], 0)
            self.assertEqual(conn.execute(
                "SELECT scraped FROM sitemap_cache WHERE loc = ?",
                (MOVIE_URL,)).fetchone()[0], 1)
        finally:
            conn.close()

    def test_re_export_is_idempotent(self):
        fh.export_staging(self.db, [self.record()])
        fh.export_staging(self.db, [self.record()])
        conn = sqlite3.connect(self.db)
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM releases").fetchone()[0], 3)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0], 6)
        finally:
            conn.close()

    def test_stats(self):
        fh.export_staging(self.db, [self.record()])
        got = fh.stats(self.db)
        self.assertEqual(got["posts"], 1)
        self.assertEqual(got["releases"], 3)
        self.assertEqual(got["sources"], 6)
        self.assertEqual(got["active_sources"], 0)


class FailureLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db = Path(self.tmp.name)
        conn = sqlite3.connect(self.db)
        fh.ensure_schema(conn)
        conn.close()

    def tearDown(self):
        self.db.unlink(missing_ok=True)

    def queue(self, loc, scraped=0, errors=0):
        conn = sqlite3.connect(self.db)
        conn.execute(
            "INSERT OR REPLACE INTO sitemap_cache (loc, lastmod, slug, scraped, "
            "raw_json, error_count) VALUES (?, NULL, ?, ?, '{}', ?);",
            (loc, fh.slug_from(loc), scraped, errors))
        conn.commit()
        conn.close()

    def test_cap_parks_with_reason(self):
        self.queue(MOVIE_URL)
        with silenced():
            for _ in range(fh.MAX_SCRAPE_ATTEMPTS):
                fh._bump_error(self.db, MOVIE_URL,
                               fh._failure("http-502", 502, MOVIE_URL, "http-502"))
        conn = sqlite3.connect(self.db)
        try:
            scraped, errors, raw = conn.execute(
                "SELECT scraped, error_count, raw_json FROM sitemap_cache "
                "WHERE loc = ?", (MOVIE_URL,)).fetchone()
        finally:
            conn.close()
        payload = json.loads(raw)
        self.assertEqual((scraped, errors), (-1, 3))
        self.assertEqual(payload["status"], "dead")
        self.assertEqual(len(payload["failures"]), 3)

    def test_pending_selection(self):
        self.queue(MOVIE_URL, scraped=2, errors=1)
        self.queue(SERIES_URL, scraped=-1, errors=3)
        conn = sqlite3.connect(self.db)
        try:
            rows = conn.execute(
                fh.PENDING_SELECT,
                (*fh.QUEUED_SCRAPE_STATES, fh.MAX_SCRAPE_ATTEMPTS)).fetchall()
        finally:
            conn.close()
        self.assertEqual([r[0] for r in rows], [MOVIE_URL])


class CrawlTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db = Path(self.tmp.name)
        conn = sqlite3.connect(self.db)
        fh.ensure_schema(conn)
        conn.execute(
            "INSERT INTO sitemap_cache (loc, lastmod, slug, scraped, raw_json, "
            "error_count) VALUES (?, NULL, ?, 0, '{}', 0);",
            (MOVIE_URL, MOVIE_SLUG))
        conn.commit()
        conn.close()
        fh.STOP_REQUESTED = False

    def tearDown(self):
        fh.STOP_REQUESTED = False
        self.db.unlink(missing_ok=True)

    def fake_get(self, url, **kwargs):
        if url == MOVIE_URL:
            return 200, url, page(links=MOVIE_LINKS), {}
        if "/all-format-downloads-" in url:
            return 200, url, bridge(3), {}
        return 404, url, "", {}

    def test_crawl_writes_post_releases_and_sources(self):
        with silenced(), mock.patch.object(fh, "http_get", side_effect=self.fake_get):
            totals = fh.crawl_pending(db_path=self.db, delay=0)
        self.assertEqual(totals["posts"], 1)
        self.assertEqual(totals["releases"], 3)
        self.assertEqual(totals["sources"], 9)

    def test_bridge_failure_keeps_the_post(self):
        def fake(url, **kwargs):
            if url == MOVIE_URL:
                return 200, url, page(links=MOVIE_LINKS), {}
            return 502, url, "", {}
        with silenced(), mock.patch.object(fh, "http_get", side_effect=fake):
            totals = fh.crawl_pending(db_path=self.db, delay=0)
        self.assertEqual(totals["posts"], 1)
        self.assertEqual(totals["sources"], 0)
        self.assertEqual(totals["bridge_errors"], 3)

    def test_no_jsonld_is_parked(self):
        with silenced(), mock.patch.object(
                fh, "http_get", return_value=(200, MOVIE_URL, page(None), {})):
            totals = fh.crawl_pending(db_path=self.db, delay=0)
        self.assertEqual(totals["posts"], 0)
        self.assertEqual(totals["dead_ids"], 1)

    def test_stop_signal_spends_no_attempt(self):
        fh.STOP_REQUESTED = True
        with silenced(), mock.patch.object(fh, "http_get") as get:
            totals = fh.crawl_pending(db_path=self.db, delay=0)
        self.assertEqual(get.call_count, 0)
        self.assertEqual(totals["posts"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
