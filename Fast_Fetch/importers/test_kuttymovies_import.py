#!/usr/bin/env python3
"""
test_kuttymovies_import.py — offline unit tests for the KuttyMovies importer.

No test touches the network: the socket is replaced with a raiser for the whole
module. Fixtures follow the shapes measured on 2026-10-29 across all 905 posts:

* the Yoast `post-sitemap.xml` mixes the homepage with post permalinks whose
  slugs end in a resolution token; only those permalinks are queued;
* the WP REST record carries `title.rendered`, `content.rendered` and
  `yoast_head_json.og_image`; the body repeats metadata as labelled lines;
* every download anchor is `linkshub.website/url.php?id=<7-hex>` with the
  quality and size in its label (`1080p [2.9GB]`), and every post has links;
* series posts either repeat the title in the `<h3>` heading or use a bare
  `S01E01T05` range, so the heading — not the title alone — decides the range;
* the bridge is a 30-second robot gate, so it is stored **unverified** and
  never followed.
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

import import_kuttymovies as km  # noqa: E402


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


MOVIE_SLUG = "toxic-2026-v2-hq-hdts-hindi-line-movie-1080p-720p-480p"
MOVIE_URL = f"https://kuttymovies.wiki/{MOVIE_SLUG}/"
PACK_SLUG = "mousetrap-2026-s01-hdrip-hindi-org-dual-audio-netflix-series-1080p-720p-480p"
PACK_URL = f"https://kuttymovies.wiki/{PACK_SLUG}/"
EP_SLUG = "ali-baba-aur-40-bhoot-2026-s01e25t28-hdrip-hindi-hotstar-web-series-1080p-720p-480p"
EP_URL = f"https://kuttymovies.wiki/{EP_SLUG}/"
POSTER = "https://img1.picour.com/2026/08/27/Toxic-20261790dbf0cf7e7293.webp"
SHOT = "https://img1.picour.com/2026/08/27/Toxic-11a5602956500a506.jpg"
LINK_A = "https://linkshub.website/url.php?id=6b79806"
LINK_B = "https://linkshub.website/url.php?id=aafcf55"
LINK_C = "https://linkshub.website/url.php?id=f6f0f87"

SITEMAP = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://kuttymovies.wiki/</loc><lastmod>2026-10-28T17:37:00+00:00</lastmod></url>
  <url><loc>{MOVIE_URL}</loc><lastmod>2026-08-29T03:17:49+00:00</lastmod></url>
  <url><loc>{MOVIE_URL}</loc><lastmod>2026-08-29T03:17:49+00:00</lastmod></url>
  <url><loc>{PACK_URL}</loc></url>
  <url><loc>https://kuttymovies.wiki/contact/</loc></url>
  <url><loc>https://kuttymovies.wiki/privacy-policy/</loc></url>
</urlset>"""


def anchors(items) -> str:
    return "".join(
        f'<p style="text-align: center"><a class="{cls}" href="{href}" '
        f'target="_blank" rel="nofollow noopener"><strong>{label}</strong></a></p>'
        for cls, href, label in items)


MOVIE_HEADING = ("Download Toxic (2026) V2 HQ HDTS Hindi (Line) Movie "
                 "1080p | 720p | 480p Links")
MOVIE_BODY = (
    f'<p><img loading="lazy" src="{POSTER}" /></p>'
    f'<h2 style="text-align: center;">Toxic (2026) V2 HQ HDTS Hindi (Line) Movie '
    f'1080p | 720p | 480p</h2>'
    '<p style="text-align: center;">IMDB Ratings: 4.2/10<br />'
    'Directed: Geethu Mohandas<br />'
    'Release date : August 26, 2026 (United States)<br />'
    'Genres: Action, Crime, Drama, Romance, Thriller<br />'
    'Languages: Hindi (Line)<br />'
    'Film Stars: Yash, Nayanthara, Kiara Advani, Huma Qureshi<br />'
    'Movie Quality: 1080p | 720p | 480p HDTC<br />'
    'File Size: 3510MB | 1540MB | 595MB<br />'
    'Storyline : As Portuguese rule crumbles in Goa, Raya rises.</p>'
    f'<h2 style="text-align: center;">Screenshot</h2><p><img src="{SHOT}" />'
    '<img src="https://img1.picour.com/2026/08/27/Toxic-2.jpg" /></p>'
    f'<h3 style="text-align: center;">{MOVIE_HEADING}</h3>'
    + anchors([("wo", LINK_A, "1080p [3.5GB]"),
               ("hsl", LINK_B, "720p [1.6GB]"),
               ("sdl", LINK_C, "480p [550MB]")])
)

PACK_BODY = (
    '<p style="text-align: center;">IMDB Ratings: 7.1/10<br />'
    'Directed: Doug Liman<br />'
    'Genres: Action, Comedy, Crime, Drama<br />'
    'Languages: Hindi ORG + English<br />'
    'Film Stars: Tom Cruise, Domhnall Gleeson</p>'
    '<h3 style="text-align: center;">Download S01E01T05 Links</h3>'
    + anchors([("wo", "https://linkshub.website/url.php?id=868b2e4", "1080p [3.4GB]"),
               ("hsl", "https://linkshub.website/url.php?id=bede9e1", "720p [1.7GB]"),
               ("sdl", "https://linkshub.website/url.php?id=8c3d9de", "480p [1.1GB]")])
    + '<h3 style="text-align: center;">Download S01E06T10 Links</h3>'
    + anchors([("wo", "https://linkshub.website/url.php?id=fbef9c7", "1080p [3.4GB]"),
               ("hsl", "https://linkshub.website/url.php?id=1667780", "720p [1.7GB]"),
               ("sdl", "https://linkshub.website/url.php?id=2d48022", "480p [1.1GB]")])
)

EP_BODY = (
    '<p style="text-align: center;">IMDB Ratings: 6.8/10<br />'
    'Directed: Bhuvanesh Shrivastava<br />'
    'Release date : September 11, 2026 (India)<br />'
    'Genres: Comedy, Horror, Mystery<br />'
    'Languages: Hindi ORG<br />'
    'Film Stars: Sagar Wadhwani, Man Singh Karamati</p>'
    '<h3 style="text-align: center;">Download Ali Baba aur 40 Bhoot (2026) '
    'S01E25T28 HDRip Hindi Hotstar Web Series 1080p | 720p | 480p Links</h3>'
    + anchors([("wo", "https://linkshub.website/url.php?id=0001aa3", "1080p [2.9GB]"),
               ("hsl", "https://linkshub.website/url.php?id=00a60f2", "720p [1.2GB]"),
               ("sdl", "https://linkshub.website/url.php?id=014770e", "480p [550MB]")])
)


def payload(slug: str, url: str, title: str, content: str, **overrides) -> dict:
    record = {
        "id": 37,
        "slug": slug,
        "link": url,
        "date": "2026-08-29T09:17:49",
        "title": {"rendered": title},
        "content": {"rendered": content},
        "yoast_head_json": {"og_image": [{"url": POSTER}]},
        "categories": [5],
    }
    record.update(overrides)
    return record


def movie_payload(**overrides) -> dict:
    record = payload(MOVIE_SLUG, MOVIE_URL,
                     "Toxic (2026) V2 HQ HDTS Hindi (Line) Movie 1080p | 720p | 480p",
                     MOVIE_BODY)
    record.update(overrides)
    return record


def pack_payload(**overrides) -> dict:
    record = payload(PACK_SLUG, PACK_URL,
                     "Mousetrap (2026) S01 HDRip Hindi ORG Dual Audio Netflix "
                     "Series 1080p | 720p | 480p", PACK_BODY)
    record.update(overrides)
    return record


def ep_payload(**overrides) -> dict:
    record = payload(EP_SLUG, EP_URL,
                     "Ali Baba aur 40 Bhoot (2026) S01E25T28 HDRip Hindi Hotstar "
                     "Web Series 1080p | 720p | 480p", EP_BODY)
    record.update(overrides)
    return record


class SitemapTests(unittest.TestCase):
    def test_only_post_urls_and_deduped(self):
        rows = km.parse_sitemap(SITEMAP)
        self.assertEqual([loc for loc, _ in rows], [MOVIE_URL, PACK_URL])

    def test_lastmod_is_kept(self):
        rows = dict(km.parse_sitemap(SITEMAP))
        self.assertEqual(rows[MOVIE_URL], "2026-08-29T03:17:49+00:00")
        self.assertIsNone(rows[PACK_URL])

    def test_homepage_and_static_pages_are_dropped(self):
        for loc in ("https://kuttymovies.wiki/",
                    "https://kuttymovies.wiki/contact/",
                    "https://kuttymovies.wiki/how-to-download/"):
            self.assertEqual(km.slug_from(loc), "")

    def test_slug_validation(self):
        self.assertEqual(km.slug_from(MOVIE_URL), MOVIE_SLUG)
        self.assertEqual(km.slug_from(MOVIE_URL.rstrip("/")), MOVIE_SLUG)

    def test_rest_url_carries_slug_and_fields(self):
        url = km.rest_url(MOVIE_SLUG)
        self.assertTrue(url.startswith(km.REST_URL + "?slug="))
        self.assertIn(MOVIE_SLUG, url)
        self.assertIn("_fields=", url)


class FieldTests(unittest.TestCase):
    def test_split_title_normal(self):
        self.assertEqual(km.split_title(
            "Toxic (2026) V2 HQ HDTS Hindi (Line) Movie 1080p | 720p | 480p")[:2],
            ("Toxic", 2026))

    def test_split_title_date_in_parens(self):
        self.assertEqual(km.split_title(
            "WWE Monday Night Raw (26th October 2026) HDRip English TV Show "
            "720p | 480p")[:2], ("WWE Monday Night Raw", 2026))

    def test_split_title_keeps_colon(self):
        self.assertEqual(km.split_title(
            "Family: Ties of Blood (2006) DVDRip ORG Hindi Dubbed Movie "
            "1080p | 720p | 480p")[:2], ("Family: Ties of Blood", 2006))

    def test_split_title_without_year_cuts_at_format(self):
        name, year, rest = km.split_title("Some Film HDRip Hindi Movie 720p")
        self.assertEqual(name, "Some Film")
        self.assertIsNone(year)
        self.assertTrue(rest.startswith("HDRip"))

    def test_season_episode_range(self):
        self.assertEqual(km.season_episode_of("Show S01E01T05 Links"), (1, 1, 5))
        self.assertEqual(km.season_episode_of("Show S01E25T28 HDRip"), (1, 25, 28))
        self.assertEqual(km.season_episode_of("Show S20E48 HDRip"), (20, 48, None))
        self.assertEqual(km.season_episode_of("Show S01 HDRip"), (1, None, None))
        self.assertEqual(km.season_episode_of("No season here"), (None, None, None))

    def test_quality_and_size(self):
        self.assertEqual(km.quality_of("1080p [3.5GB]"), "1080p")
        self.assertEqual(km.quality_of("4k [20GB]"), "2160p")
        self.assertEqual(km.size_bytes("1080p [3.5GB]"), int(3.5 * 1024 ** 3))
        self.assertEqual(km.size_bytes("480p [550MB]"), int(550 * 1024 ** 2))
        self.assertIsNone(km.size_bytes("1080p"))

    def test_format(self):
        self.assertEqual(km.format_of("HDRip", "1080p [2.9GB]"), "HDRIP")
        self.assertEqual(km.format_of("WEB-DL"), "WEB-DL")
        self.assertIsNone(km.format_of("1080p [3.5GB]"))

    def test_meta_lines(self):
        meta = km.meta_lines(MOVIE_BODY)
        self.assertEqual(meta["imdb ratings"], "4.2/10")
        self.assertEqual(meta["directed"], "Geethu Mohandas")
        self.assertEqual(meta["release date"], "August 26, 2026 (United States)")
        self.assertTrue(meta["genres"].startswith("Action, Crime"))
        self.assertEqual(meta["languages"], "Hindi (Line)")
        self.assertIn("Yash", meta["film stars"])
        self.assertTrue(meta["storyline"].startswith("As Portuguese rule"))

    def test_meta_lines_released_date_spelling(self):
        meta = km.meta_lines("<p>Released Date: 25 August 2017 (UK)</p>")
        self.assertEqual(meta["release date"], "25 August 2017 (UK)")

    def test_languages_dedupe(self):
        self.assertEqual(km.languages_for("Hindi ORG + English", "Hindi"), ["Hindi", "English"])
        self.assertEqual(km.languages_for(None, "no language"), [])

    def test_split_names(self):
        self.assertEqual(km.split_names("Yash, Nayanthara and Huma Qureshi"),
                         ["Yash", "Nayanthara", "Huma Qureshi"])


class ReleaseTests(unittest.TestCase):
    def test_movie_anchors_become_releases(self):
        releases = km.releases_from_content(MOVIE_BODY, "Toxic", None, None,
                                            MOVIE_URL, ["Hindi"])
        self.assertEqual(len(releases), 3)
        self.assertEqual([r["quality"] for r in releases],
                         ["1080p", "720p", "480p"])
        self.assertEqual(releases[0]["size_bytes"], int(3.5 * 1024 ** 3))
        self.assertEqual(releases[0]["label"], "Toxic [1080p]")
        self.assertIsNone(releases[0]["season_number"])
        self.assertIsNone(releases[0]["episode_number"])
        self.assertEqual(json.loads(releases[0]["audio_languages"]), ["Hindi"])

    def test_bridge_sources_are_unverified_and_unfollowed(self):
        releases = km.releases_from_content(MOVIE_BODY, "Toxic", None, None,
                                            MOVIE_URL, [])
        src = releases[0]["sources"][0]
        self.assertEqual(src["service"], "linkshub")
        self.assertEqual(src["status"], "unverified")
        self.assertIsNone(src["final_url"])
        self.assertEqual(src["playback_type"], "download")
        self.assertEqual(src["is_temporary"], 0)
        self.assertEqual(src["resource_id"], "6b79806")
        self.assertEqual(src["source_url"], LINK_A)
        self.assertEqual(releases[0]["bridge_url"], LINK_A)

    def test_series_pack_ranges_come_from_the_heading(self):
        releases = km.releases_from_content(PACK_BODY, "Mousetrap", 1, None,
                                            PACK_URL, [])
        self.assertEqual(len(releases), 6)
        self.assertEqual([(r["season_number"], r["episode_number"],
                           r["raw_meta"]["episode_end"]) for r in releases],
                         [(1, 1, 5), (1, 1, 5), (1, 1, 5),
                          (1, 6, 10), (1, 6, 10), (1, 6, 10)])
        self.assertEqual(releases[0]["label"], "Mousetrap S01E01-E05 [1080p]")
        self.assertEqual(releases[3]["label"], "Mousetrap S01E06-E10 [1080p]")

    def test_episode_heading_overrides_the_title(self):
        releases = km.releases_from_content(EP_BODY, "Ali Baba aur 40 Bhoot", 1, 25,
                                            EP_URL, [])
        self.assertEqual(len(releases), 3)
        self.assertEqual((releases[0]["season_number"],
                          releases[0]["episode_number"],
                          releases[0]["raw_meta"]["episode_end"]), (1, 25, 28))
        self.assertEqual(releases[0]["label"],
                         "Ali Baba aur 40 Bhoot S01E25-E28 [1080p]")

    def test_foreign_and_malformed_links_are_ignored(self):
        html = ('<h3>Download</h3>'
                '<a href="https://t.me/HelloFilmyHub">Telegram</a>'
                '<a href="https://linkshub.website/url.php?id=ZZZ">1080p [1GB]</a>'
                '<a href="https://example.com/url.php?id=6b79806">720p [1GB]</a>')
        self.assertEqual(km.releases_from_content(html, "X", None, None, MOVIE_URL, []), [])

    def test_anchor_without_quality_is_skipped(self):
        html = ('<h3>Download</h3>'
                '<a href="https://linkshub.website/url.php?id=6b79806">Mirror</a>')
        self.assertEqual(km.releases_from_content(html, "X", None, None, MOVIE_URL, []), [])


class BuildRecordTests(unittest.TestCase):
    def test_movie_record_fields(self):
        record = km.build_record(MOVIE_URL, movie_payload())
        self.assertEqual(record["canonical_key"], MOVIE_SLUG)
        self.assertEqual(record["title"], "Toxic")
        self.assertEqual(record["year"], 2026)
        self.assertEqual(record["media_type"], "movie")
        self.assertEqual(record["imdb_rating"], "4.2")
        self.assertEqual(record["director"], "Geethu Mohandas")
        self.assertEqual(json.loads(record["genres"])[:2], ["Action", "Crime"])
        self.assertEqual(json.loads(record["cast_names"])[0], "Yash")
        self.assertEqual(json.loads(record["languages"]), ["Hindi"])
        self.assertEqual(record["poster_url"], POSTER)
        self.assertEqual(record["backdrop_url"], SHOT)
        self.assertEqual(len(json.loads(record["backdrop_urls"])), 2)
        self.assertIn("Portuguese", record["synopsis"])
        self.assertEqual(record["release_date"], "August 26, 2026 (United States)")
        self.assertIsNone(record["seasons"])
        self.assertEqual(len(record["releases"]), 3)

    def test_series_pack_record(self):
        record = km.build_record(PACK_URL, pack_payload())
        self.assertEqual(record["media_type"], "series")
        self.assertEqual(json.loads(record["seasons"]), [1])
        self.assertEqual(len(record["releases"]), 6)
        self.assertEqual(json.loads(record["languages"]), ["Hindi", "English"])

    def test_episode_record(self):
        record = km.build_record(EP_URL, ep_payload())
        self.assertEqual(record["media_type"], "series")
        self.assertEqual(record["releases"][0]["episode_number"], 25)
        self.assertEqual(record["raw_meta"]["episode_range_end"], 28)

    def test_season_only_title(self):
        season_only = (
            '<p style="text-align: center;">IMDB Ratings: 5.5/10<br />'
            'Genres: Drama<br />'
            'Languages: Hindi ORG</p>'
            '<h3 style="text-align: center;">Download Friends Sex and Games (2026) '
            'S01 HDRip Hindi ORG Dual Audio Amazon Web Series 1080p | 720p | 480p '
            'Links</h3>'
            + anchors([("wo", "https://linkshub.website/url.php?id=0aa0001",
                        "1080p [2.2GB]")]))
        record = km.build_record(PACK_URL, pack_payload(content=season_only, title={
            "rendered": "Friends Sex and Games (2026) S01 HDRip Hindi ORG Dual "
                        "Audio Amazon Web Series 1080p | 720p | 480p"}))
        self.assertEqual(record["media_type"], "series")
        self.assertEqual(record["releases"][0]["season_number"], 1)
        self.assertIsNone(record["releases"][0]["episode_number"])
        self.assertEqual(record["releases"][0]["label"],
                         "Friends Sex and Games S01 [1080p]")

    def test_adult_and_animated_flags(self):
        adult = km.build_record(MOVIE_URL, payload(
            MOVIE_SLUG, MOVIE_URL, "I Want Your Sex (2026) HDRip English Movie "
            "1080p | 720p | 480p", MOVIE_BODY))
        self.assertEqual(adult["is_18_plus"], 1)
        cartoon = km.build_record(MOVIE_URL, payload(
            MOVIE_SLUG, MOVIE_URL, "Toon (2024) HDRip Hindi Movie 1080p | 720p",
            MOVIE_BODY.replace("Action, Crime, Drama, Romance, Thriller",
                               "Animation, Comedy")))
        self.assertEqual(cartoon["is_animated"], 1)
        self.assertEqual(cartoon["is_18_plus"], 0)

    def test_no_title_returns_none(self):
        self.assertIsNone(km.build_record(MOVIE_URL, payload(
            MOVIE_SLUG, MOVIE_URL, "", MOVIE_BODY)))

    def test_entity_in_title_is_decoded(self):
        record = km.build_record(
            MOVIE_URL, payload(MOVIE_SLUG, MOVIE_URL,
                               "C/O Sarangkot &amp; Co (2026) HDRip Bengali Movie "
                               "1080p | 720p | 480p", MOVIE_BODY))
        self.assertEqual(record["title"], "C/O Sarangkot & Co")


class StagingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db = Path(self.tmp.name)

    def tearDown(self):
        self.db.unlink(missing_ok=True)

    def record(self):
        return km.build_record(PACK_URL, pack_payload())

    def test_export_writes_rows_and_marks_cache(self):
        result = km.export_staging(self.db, [self.record()])
        self.assertEqual(result["posts_written"], 1)
        self.assertEqual(result["releases_written"], 6)
        self.assertEqual(result["sources_written"], 6)
        conn = sqlite3.connect(self.db)
        try:
            self.assertEqual(conn.execute(
                "SELECT COUNT(*) FROM sources WHERE status = 'active'").fetchone()[0], 0)
            self.assertEqual(conn.execute(
                "SELECT scraped FROM sitemap_cache WHERE loc = ?",
                (PACK_URL,)).fetchone()[0], 1)
        finally:
            conn.close()

    def test_re_export_is_idempotent(self):
        km.export_staging(self.db, [self.record()])
        km.export_staging(self.db, [self.record()])
        conn = sqlite3.connect(self.db)
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM releases").fetchone()[0], 6)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0], 6)
        finally:
            conn.close()

    def test_shrinking_post_replaces_stale_releases(self):
        km.export_staging(self.db, [self.record()])
        one_link = PACK_BODY.split('<h3 style="text-align: center;">Download S01E06T10')[0]
        smaller = km.build_record(PACK_URL, pack_payload(content=one_link))
        km.export_staging(self.db, [smaller])
        conn = sqlite3.connect(self.db)
        try:
            self.assertEqual(conn.execute(
                "SELECT COUNT(*) FROM releases WHERE post_canonical_key = ?",
                (PACK_SLUG,)).fetchone()[0], 3)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0], 3)
        finally:
            conn.close()

    def test_media_type_and_flags_are_clamped(self):
        bad = self.record()
        bad["media_type"] = "webinar"
        bad["is_18_plus"] = None
        km.export_staging(self.db, [bad])
        conn = sqlite3.connect(self.db)
        try:
            self.assertEqual(conn.execute(
                "SELECT media_type, is_18_plus FROM posts").fetchone(), ("movie", 0))
        finally:
            conn.close()

    def test_stats(self):
        km.export_staging(self.db, [self.record()])
        got = km.stats(self.db)
        self.assertEqual(got["posts"], 1)
        self.assertEqual(got["series"], 1)
        self.assertEqual(got["releases"], 6)
        self.assertEqual(got["sources"], 6)
        self.assertEqual(got["active_sources"], 0)
        self.assertEqual(got["unverified_sources"], 6)


class FailureLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db = Path(self.tmp.name)
        conn = sqlite3.connect(self.db)
        km.ensure_schema(conn)
        conn.close()

    def tearDown(self):
        self.db.unlink(missing_ok=True)

    def queue(self, loc, scraped=0, errors=0):
        conn = sqlite3.connect(self.db)
        conn.execute(
            "INSERT OR REPLACE INTO sitemap_cache (loc, lastmod, slug, scraped, "
            "raw_json, error_count) VALUES (?, NULL, ?, ?, '{}', ?);",
            (loc, km.slug_from(loc), scraped, errors))
        conn.commit()
        conn.close()

    def test_cap_parks_with_reason(self):
        self.queue(MOVIE_URL)
        with silenced():
            for _ in range(km.MAX_SCRAPE_ATTEMPTS):
                km._bump_error(self.db, MOVIE_URL,
                               km._failure("http-520", 520, MOVIE_URL, "http-520"))
        conn = sqlite3.connect(self.db)
        try:
            scraped, errors, raw = conn.execute(
                "SELECT scraped, error_count, raw_json FROM sitemap_cache "
                "WHERE loc = ?", (MOVIE_URL,)).fetchone()
        finally:
            conn.close()
        payload_ = json.loads(raw)
        self.assertEqual((scraped, errors), (-1, 3))
        self.assertEqual(payload_["status"], "dead")
        self.assertEqual(payload_["last_error"], "http-520")
        self.assertEqual([f["attempt"] for f in payload_["failures"]], [1, 2, 3])

    def test_park_now_is_immediate(self):
        self.queue(MOVIE_URL)
        with silenced():
            km._bump_error(self.db, MOVIE_URL,
                           km._failure("rest-empty", 200, MOVIE_URL, "slug gone"),
                           park_now=True)
        conn = sqlite3.connect(self.db)
        try:
            self.assertEqual(conn.execute(
                "SELECT scraped FROM sitemap_cache WHERE loc = ?",
                (MOVIE_URL,)).fetchone()[0], -1)
        finally:
            conn.close()

    def test_pending_selection(self):
        self.queue(MOVIE_URL, scraped=2, errors=1)
        self.queue(PACK_URL, scraped=-1, errors=3)
        self.queue(EP_URL, scraped=1, errors=0)
        conn = sqlite3.connect(self.db)
        try:
            rows = conn.execute(
                km.PENDING_SELECT,
                (*km.QUEUED_SCRAPE_STATES, km.MAX_SCRAPE_ATTEMPTS)).fetchall()
        finally:
            conn.close()
        self.assertEqual([r[0] for r in rows], [MOVIE_URL])


class CrawlTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db = Path(self.tmp.name)
        conn = sqlite3.connect(self.db)
        km.ensure_schema(conn)
        conn.execute(
            "INSERT INTO sitemap_cache (loc, lastmod, slug, scraped, raw_json, "
            "error_count) VALUES (?, NULL, ?, 0, '{}', 0);",
            (MOVIE_URL, MOVIE_SLUG))
        conn.commit()
        conn.close()
        km.STOP_REQUESTED = False

    def tearDown(self):
        km.STOP_REQUESTED = False
        self.db.unlink(missing_ok=True)

    def body(self, record):
        return json.dumps([record])

    def test_crawl_reads_rest_and_writes_rows(self):
        def fake(url, **kwargs):
            self.assertIn(MOVIE_SLUG, url)
            return 200, url, self.body(movie_payload()), {}
        with silenced(), mock.patch.object(km, "http_get", side_effect=fake):
            totals = km.crawl_pending(db_path=self.db, delay=0)
        self.assertEqual((totals["posts"], totals["releases"], totals["sources"]),
                         (1, 3, 3))

    def test_rest_empty_parks_the_row(self):
        with silenced(), mock.patch.object(km, "http_get",
                                           return_value=(200, MOVIE_URL, "[]", {})):
            totals = km.crawl_pending(db_path=self.db, delay=0)
        self.assertEqual(totals["failed_rows"], 1)
        self.assertEqual(totals["parked"], 1)
        conn = sqlite3.connect(self.db)
        try:
            scraped, raw = conn.execute(
                "SELECT scraped, raw_json FROM sitemap_cache WHERE loc = ?",
                (MOVIE_URL,)).fetchone()
        finally:
            conn.close()
        self.assertEqual(scraped, -1)
        self.assertEqual(json.loads(raw)["failures"][0]["kind"], "rest-empty")

    def test_http_404_parks_immediately(self):
        with silenced(), mock.patch.object(km, "http_get",
                                           return_value=(404, MOVIE_URL, "", {})):
            totals = km.crawl_pending(db_path=self.db, delay=0)
        self.assertEqual(totals["failed_rows"], 1)
        self.assertEqual(totals["parked"], 1)
        conn = sqlite3.connect(self.db)
        try:
            self.assertEqual(conn.execute(
                "SELECT scraped FROM sitemap_cache WHERE loc = ?",
                (MOVIE_URL,)).fetchone()[0], -1)
        finally:
            conn.close()

    def test_transient_http_stays_retryable(self):
        with silenced(), mock.patch.object(km, "http_get",
                                           return_value=(520, MOVIE_URL, "", {})):
            totals = km.crawl_pending(db_path=self.db, delay=0)
        self.assertEqual(totals["failed_rows"], 1)
        self.assertEqual(totals["parked"], 0)
        conn = sqlite3.connect(self.db)
        try:
            scraped, errors = conn.execute(
                "SELECT scraped, error_count FROM sitemap_cache WHERE loc = ?",
                (MOVIE_URL,)).fetchone()
        finally:
            conn.close()
        self.assertEqual((scraped, errors), (2, 1))

    def test_bad_json_stays_retryable(self):
        with silenced(), mock.patch.object(km, "http_get",
                                           return_value=(200, MOVIE_URL, "<html>", {})):
            km.crawl_pending(db_path=self.db, delay=0)
        conn = sqlite3.connect(self.db)
        try:
            self.assertEqual(conn.execute(
                "SELECT scraped FROM sitemap_cache WHERE loc = ?",
                (MOVIE_URL,)).fetchone()[0], 2)
        finally:
            conn.close()

    def test_post_without_links_stays_retryable(self):
        bare = movie_payload(content="<p>No downloads yet.</p>")
        with silenced(), mock.patch.object(km, "http_get",
                                           return_value=(200, MOVIE_URL,
                                                         self.body(bare), {})):
            km.crawl_pending(db_path=self.db, delay=0)
        conn = sqlite3.connect(self.db)
        try:
            scraped, raw = conn.execute(
                "SELECT scraped, raw_json FROM sitemap_cache WHERE loc = ?",
                (MOVIE_URL,)).fetchone()
        finally:
            conn.close()
        self.assertEqual(scraped, 2)
        self.assertEqual(json.loads(raw)["failures"][0]["kind"], "no-links")

    def test_stop_signal_spends_no_attempt(self):
        km.STOP_REQUESTED = True
        with silenced(), mock.patch.object(km, "http_get") as get:
            totals = km.crawl_pending(db_path=self.db, delay=0)
        self.assertEqual(get.call_count, 0)
        self.assertEqual(totals["posts"], 0)

    def test_a_429_pauses_the_crawl_without_burning_the_queue(self):
        second = "https://kuttymovies.wiki/zz-second-2026-hindi-movie-1080p/"
        conn = sqlite3.connect(self.db)
        conn.execute(
            "INSERT INTO sitemap_cache (loc, lastmod, slug, scraped, raw_json, "
            "error_count) VALUES (?, NULL, ?, 0, '{}', 0);",
            (second, "zz-second-2026-hindi-movie-1080p"))
        conn.commit()
        conn.close()
        with silenced(), mock.patch.object(
                km, "http_get", return_value=(429, MOVIE_URL, "", {})) as get:
            totals = km.crawl_pending(db_path=self.db, delay=0)
        self.assertTrue(totals["paused_rate_limit"])
        self.assertEqual(get.call_count, 1, "the crawl must stop on the first 429")
        conn = sqlite3.connect(self.db)
        try:
            states = dict(conn.execute(
                "SELECT loc, scraped FROM sitemap_cache").fetchall())
        finally:
            conn.close()
        self.assertEqual(states[MOVIE_URL], 2)
        self.assertEqual(states[second], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
