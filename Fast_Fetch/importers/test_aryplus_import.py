#!/usr/bin/env python3
"""
test_aryplus_import.py — offline unit tests for the ARY Plus staging importer.

No test reaches the network and no test opens a database other than a temp file:
the socket is replaced with a raiser for the whole module, and every reader is
exercised against fixtures shaped from the live pages measured on 2026-10-28
(see the importer docstring). The rules this suite exists to keep:

* a stale sitemap id (5,208-byte app shell) never becomes a post;
* a stream row may only name vod.aryzap.com, and only as the durable master URL;
* episodes are releases; the series-level URL is the trailer; a single video's
  URL is the full release even though the site calls it a "trailer";
* an encrypted (`drmEnabled`) episode is stored blocked, never active.
"""

from __future__ import annotations

import contextlib
import io
import json
import socket
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import import_aryplus as ap  # noqa: E402


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


TITLE_ID = "6a35241e62c5104b7d23fbd0"
TITLE_URL = f"https://aryplus.tv/title/{TITLE_ID}"
HLS_A = ("https://vod.aryzap.com/c9b8f8d2vodtransth1313565080/"
         "b9471e535001834807666899482/adp.10.m3u8")
HLS_B = ("https://vod.aryzap.com/c9b8f8d2vodtransth1313565080/"
         "188dc79f5001834807671336606/adp.10.m3u8")
TRAILER = ("https://vod.aryzap.com/be8170a0vodtranssgp1313565080/"
           "b4d996d65001834820510019954/adp.10.m3u8")
BANNER = "https://images.aryplus.tv/desktop/Desktop-Cover-1920x1080-Without-Logo_1.webp"
LOGO = "https://images.aryplus.tv/logo/Logo_1.webp"
POSTER = "https://images.aryplus.tv/big/Big-Cover-1280x720-With-Logo_1.webp"


def episode(number: int, source: str = HLS_A, **overrides) -> dict:
    row = {
        "_id": f"{number:024x}",
        "seriesId": TITLE_ID,
        "videoEpNumber": number,
        "videoSource": source,
        "title": f"Episode {number}",
        "description": f"Episode {number} description",
        "imagePathV2": f"cdnv2/EP_{number}_1.webp",
        "videoLength": "2388",
        "videoType": "episode",
        "published": "true",
        "status": "published",
        "drmEnabled": False,
        "subtitles": [],
    }
    row.update(overrides)
    return row


def ld_block(**overrides) -> dict:
    block = {
        "@context": "https://schema.org",
        "@type": "TVSeries",
        "url": TITLE_URL,
        "contentRating": "16+",
        "name": "Mein Chand Si",
        "description": "A story about Irsa (Saba Qamar) and Salaar (Sami Khan).",
        "genre": ["Drama"],
        "image": POSTER,
        "trailer": {
            "@type": "VideoObject",
            "name": "Mein Chand Si - Trailer",
            "contentUrl": TRAILER,
            "duration": "00:02:30",
            "thumbnailUrl": POSTER,
            "uploadDate": "2017-06-10T00:00:00.000Z",
        },
        "dateCreated": "2017-06-10T00:00:00.000Z",
        "startDate": "2017-06-10",
        "numberOfSeasons": 1,
        "actors": [{"@type": "Person", "name": "Saba Qamar"},
                   {"@type": "Person", "name": "Sami Khan"}],
        "directors": [],
    }
    block.update(overrides)
    return block


def page(ld: dict | None, episodes: list | None = None, banner: str = BANNER,
         logo: str = LOGO, video: str = TRAILER, title: str = "Mein Chand Si",
         year: str = "2017", keywords: str = "Saba Qamar,Sami Khan") -> str:
    blocks = []
    lead = ('{"_id":"%s","year":"%s","bannerUrl":"%s","videoUrl":"%s",'
            '"title":"%s","logoUrl":"%s"}') % (TITLE_ID, year, banner, video, title, logo)
    blocks.append("18:" + lead)
    if episodes is not None:
        blocks.append("20:" + json.dumps(["$", "$L25", None, {"episodes": episodes}]))
    rsc = "".join(
        f"<script>self.__next_f.push({json.dumps([1, block])})</script>"
        for block in blocks)
    ld_html = ""
    if ld is not None:
        ld_html = (f'<script type="application/ld+json">'
                   f"{json.dumps(ld, ensure_ascii=False)}</script>")
    return (f"<!doctype html><html><head><title>Watch {title} | ARY Plus</title>"
            f'<meta name="keywords" content="{keywords}"/>{ld_html}</head>'
            f"<body>{rsc}</body></html>")


class SitemapTests(unittest.TestCase):
    def test_parse_index_and_urlset(self):
        index = ("<sitemapindex><sitemap><loc>https://aryplus.tv/sitemap/"
                 "6adf9e8872235fabf9cebdba.xml</loc></sitemap></sitemapindex>")
        self.assertEqual(ap.parse_locs(index),
                         ["https://aryplus.tv/sitemap/6adf9e8872235fabf9cebdba.xml"])
        urlset = (f"<urlset><url><loc>{TITLE_URL}</loc></url></urlset>")
        self.assertEqual(ap.parse_locs(urlset), [TITLE_URL])

    def test_title_id_only_accepts_the_measured_shape(self):
        self.assertEqual(ap.title_id(TITLE_URL), TITLE_ID)
        self.assertEqual(ap.title_id(f"{TITLE_URL}?x=1"), "")
        self.assertEqual(ap.title_id("https://aryplus.tv/title/nothex"), "")

    def test_genre_sitemap_is_not_a_title(self):
        self.assertIsNone(ap.HEX_SITEMAP_RE.search("https://aryplus.tv/sitemap-genres.xml"))


class PayloadTests(unittest.TestCase):
    def test_rsc_payload_joins_blocks_and_unescapes(self):
        html = page(ld_block(), [episode(1), episode(2)])
        rsc = ap.rsc_payload(html)
        self.assertIn('"episodes"', rsc)
        self.assertIn('"bannerUrl":"', rsc)
        rows = ap.find_episodes(rsc)
        self.assertEqual([r["videoEpNumber"] for r in rows], [1, 2])

    def test_json_array_after_survives_brackets_inside_strings(self):
        text = 'x:"rows":[{"note":"a ] b [ c"}] tail'
        self.assertEqual(ap.json_array_after(text, "rows"),
                         [{"note": "a ] b [ c"}])

    def test_json_array_after_returns_none_when_absent(self):
        self.assertIsNone(ap.json_array_after("nothing here", "episodes"))

    def test_dead_shell_has_no_record(self):
        shell = '<html><head><title>ARY PLUS - A Video Streaming Portal</title>' \
                "</head><body><div id=\"app\"></div></body></html>"
        self.assertIsNone(ap.parse_title_page(shell, TITLE_URL))


class SeriesRecordTests(unittest.TestCase):
    def record(self, **overrides):
        html = page(ld_block(**overrides), [episode(1), episode(2)])
        record = ap.parse_title_page(html, TITLE_URL)
        self.assertIsNotNone(record)
        return record

    def test_catalog_fields(self):
        record = self.record()
        self.assertEqual(record["canonical_key"], f"aryplus:{TITLE_ID}")
        self.assertEqual(record["clean_title"], "Mein Chand Si")
        self.assertEqual(record["year"], 2017)
        self.assertEqual(record["media_type"], "series")
        self.assertEqual(record["genres"], "Drama")
        self.assertEqual(record["cast_names"], "Saba Qamar, Sami Khan")
        self.assertEqual(record["languages"], "Urdu")
        self.assertEqual(record["industry"], "Pakistani")
        self.assertEqual(record["country"], "PK")
        self.assertEqual(record["poster_url"], POSTER)
        self.assertEqual(record["backdrop_url"], BANNER)
        self.assertEqual(record["raw_meta"]["logo_url"], LOGO)
        self.assertEqual(record["raw_meta"]["content_rating"], "16+")
        self.assertEqual(record["is_18_plus"], 0)
        self.assertIn("Irsa", record["synopsis"])

    def test_episodes_become_releases_and_trailer_is_separate(self):
        record = self.record()
        labels = [r["label"] for r in record["releases"]]
        self.assertEqual(labels, ["Trailer", "Episode 1", "Episode 2"])
        trailer, first, second = record["releases"]
        self.assertEqual(trailer["episode_number"], 0)
        self.assertEqual(first["episode_number"], 1)
        self.assertEqual(first["season_number"], 1)
        self.assertEqual(second["episode_number"], 2)
        self.assertEqual(record["raw_meta"]["episodes_published"], 2)
        self.assertEqual(record["raw_meta"]["episode_seconds_total"], 4776)

    def test_every_source_is_the_durable_master_url(self):
        record = self.record()
        sources = [s for rel in record["releases"] for s in rel["sources"]]
        self.assertEqual(len(sources), 3)
        for src in sources:
            self.assertEqual(src["service"], "aryzap-vod")
            self.assertEqual(src["playback_type"], "hls")
            self.assertTrue(src["source_url"].startswith("https://vod.aryzap.com/"))
            self.assertIn("adp.10.m3u8", src["source_url"])
            self.assertEqual(src["source_url"], src["final_url"])
            self.assertEqual(src["is_temporary"], 0)
            self.assertEqual(src["status"], "unverified")
            self.assertNotIn("token", src["source_url"].lower())

    def test_series_trailer_url_is_not_duplicated_as_an_episode(self):
        record = self.record()
        episode_sources = {r["sources"][0]["source_url"]
                           for r in record["releases"] if r["episode_number"] != 0}
        self.assertNotIn(TRAILER, episode_sources)

    def test_unpublished_episode_is_filtered(self):
        unpublished = episode(3, published="false", status="draft")
        html = page(ld_block(), [episode(1), unpublished])
        record = ap.parse_title_page(html, TITLE_URL)
        self.assertEqual([r["episode_number"] for r in record["releases"]], [0, 1])

    def test_year_falls_back_to_the_rsc_year(self):
        block = ld_block()
        block.pop("dateCreated")
        block.pop("startDate")
        record = ap.parse_title_page(page(block, [episode(1)], year="2019"), TITLE_URL)
        self.assertEqual(record["year"], 2019)

    def test_adult_rating_sets_the_flag(self):
        record = self.record(contentRating="18+")
        self.assertEqual(record["is_18_plus"], 1)

    def test_drm_episode_is_blocked_not_active(self):
        html = page(ld_block(), [episode(1, drmEnabled=True)])
        record = ap.parse_title_page(html, TITLE_URL)
        self.assertEqual(record["raw_meta"]["episodes_drm"], 1)
        blocked = [r for r in record["releases"] if r["episode_number"] == 1]
        self.assertEqual(blocked[0]["sources"][0]["status"], "blocked")

    def test_foreign_host_is_rejected(self):
        html = page(ld_block(), [episode(1, source="https://evil.example.com/x.m3u8")])
        record = ap.parse_title_page(html, TITLE_URL)
        self.assertEqual(record["raw_meta"]["episodes_rejected_host"], 1)
        playable = [r for r in record["releases"] if r["episode_number"] != 0]
        self.assertEqual(playable, [])

    def test_subtitle_tracks_are_captured_in_raw_meta(self):
        tracks = [{"url": "cdnv2/sub_1.vtt", "language": "en"}]
        html = page(ld_block(), [episode(1, subtitles=tracks)])
        record = ap.parse_title_page(html, TITLE_URL)
        self.assertEqual(record["raw_meta"]["subtitles_tracks"], 1)
        self.assertEqual(record["raw_meta"]["subtitle_tracks"],
                         [{"episode": 1, "url": "https://images.aryplus.tv/cdnv2/sub_1.vtt",
                           "language": "en"}])


class SingleVideoTests(unittest.TestCase):
    def test_movie_url_is_the_full_release_not_a_trailer(self):
        block = ld_block(**{
            "@type": "Movie",
            "name": "Jahez Mubarak",
            "genre": ["Comedy", "Telefilm"],
            "trailer": {"@type": "VideoObject", "name": "Jahez Mubarak - Trailer",
                        "contentUrl": TRAILER, "duration": "01:18:02"},
        })
        record = ap.parse_title_page(page(block, None, video=TRAILER,
                                          title="Jahez Mubarak"), TITLE_URL)
        self.assertEqual(record["media_type"], "movie")
        self.assertEqual(record["duration"], "01:18:02")
        self.assertEqual(len(record["releases"]), 1)
        release = record["releases"][0]
        self.assertEqual(release["label"], "Full")
        self.assertIsNone(release["episode_number"])
        self.assertEqual(release["sources"][0]["source_url"], TRAILER)
        self.assertEqual(record["raw_meta"]["episode_seconds_total"], 4682)

    def test_ost_without_a_stream_keeps_metadata_and_invents_nothing(self):
        block = ld_block(**{"@type": "Movie", "name": "Cheekh OST",
                            "genre": ["OST"], "trailer": {}})
        record = ap.parse_title_page(page(block, None, video="$undefined",
                                          title="Cheekh OST"), TITLE_URL)
        self.assertEqual(record["clean_title"], "Cheekh OST")
        self.assertEqual(record["releases"], [])
        self.assertEqual(record["raw_meta"]["episodes_without_stream"], 1)
        self.assertEqual(record["poster_url"], POSTER)


class VerifyTests(unittest.TestCase):
    class Response:
        def __init__(self, status: int, body: str, content_type: str):
            self.status = status
            self.body = body.encode()
            self.headers = {"content-type": content_type}

        def read(self, size: int = -1):
            return self.body[:size] if size and size > 0 else self.body

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_open(self, response):
        return mock.patch.object(ap, "_open", return_value=response)

    def test_active_master_playlist(self):
        body = ("#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1,RESOLUTION=426x240\n"
                "a.m3u8\n#EXT-X-STREAM-INF:BANDWIDTH=2,RESOLUTION=1920x1080\nb.m3u8\n")
        with self.fake_open(self.Response(200, body, "application/vnd.apple.mpegurl")):
            verdict = ap.verify_hls(HLS_A)
        self.assertEqual(verdict["status"], "active")
        self.assertTrue(verdict["is_hls"])
        self.assertEqual(verdict["variants"], 2)
        self.assertEqual(verdict["best_resolution"], "1920x1080")

    def test_encrypted_playlist_is_blocked(self):
        body = ("#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI=\"k.bin\"\n"
                "#EXTINF:6,\nseg.ts\n")
        with self.fake_open(self.Response(200, body, "application/vnd.apple.mpegurl")):
            verdict = ap.verify_hls(HLS_A)
        self.assertTrue(verdict["drm"])
        self.assertEqual(verdict["status"], "blocked")

    def test_http_403_is_blocked_and_404_is_dead(self):
        with self.fake_open(urllib.error.HTTPError(HLS_A, 403, "forbidden", {}, None)):
            verdict = ap.verify_hls(HLS_A)
        self.assertEqual(verdict["status"], "blocked")
        with self.fake_open(urllib.error.HTTPError(HLS_A, 404, "gone", {}, None)):
            verdict = ap.verify_hls(HLS_A)
        self.assertEqual(verdict["status"], "dead")

    def test_html_200_is_dead(self):
        with self.fake_open(self.Response(200, "<html>nope</html>", "text/html")):
            verdict = ap.verify_hls(HLS_A)
        self.assertFalse(verdict["is_hls"])
        self.assertEqual(verdict["status"], "dead")

    def test_transport_failure_is_unverified_and_not_retried(self):
        calls = []

        def boom(*args, **kwargs):
            calls.append(1)
            raise OSError("dns down")

        with mock.patch.object(ap, "_open", side_effect=boom):
            verdict = ap.verify_hls(HLS_A)
        self.assertEqual(verdict["status"], "unverified")
        self.assertEqual(len(calls), 1)


class StagingTests(unittest.TestCase):
    def record(self):
        return ap.parse_title_page(page(ld_block(), [episode(1), episode(2)]), TITLE_URL)

    def test_export_writes_posts_releases_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "aryplus.db"
            totals = ap.export_staging(db, [self.record()])
            self.assertEqual(totals["posts_written"], 1)
            self.assertEqual(totals["releases_written"], 3)
            self.assertEqual(totals["sources_written"], 3)
            report = ap.stats(db)
            self.assertEqual(report["posts"], 1)
            self.assertEqual(report["releases"], 3)
            self.assertEqual(report["sources"], 3)
            self.assertEqual(report["playback_types"], {"hls": 3})
            self.assertEqual(report["source_status"], {"unverified": 3})
            self.assertEqual(report["media_types"], {"series": 1})
            self.assertEqual(report["episodes"], 2)
            self.assertEqual(report["indexed"], 1)

    def test_re_export_replaces_releases_without_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "aryplus.db"
            ap.export_staging(db, [self.record()])
            ap.export_staging(db, [self.record()])
            report = ap.stats(db)
            self.assertEqual(report["releases"], 3)
            self.assertEqual(report["sources"], 3)

    def test_export_keeps_the_adult_flag_sticky(self):
        adult = self.record()
        adult["is_18_plus"] = 1
        clean = self.record()
        clean["is_18_plus"] = 0
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "aryplus.db"
            ap.export_staging(db, [adult])
            ap.export_staging(db, [clean])
            self.assertEqual(ap.stats(db)["adult_flagged"], 1)

    def test_export_skips_a_record_without_a_title(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "aryplus.db"
            totals = ap.export_staging(db, [{"canonical_key": "x", "clean_title": ""}])
            self.assertEqual(totals["skipped"], 1)
            self.assertEqual(ap.stats(db)["posts"], 0)


class CrawlParseTests(unittest.TestCase):
    def test_dead_shell_is_parked(self):
        record, verdict = ap._parse_record(TITLE_URL, '{"id":"x"}',
                                           "<html><body>shell</body></html>")
        self.assertIsNone(record)
        self.assertEqual(verdict, "no-jsonld")

    def test_empty_page_is_requeued(self):
        record, verdict = ap._parse_record(TITLE_URL, '{"id":"x"}', "   ")
        self.assertIsNone(record)
        self.assertEqual(verdict, "empty-page")

    def test_live_page_keeps_its_queue_payload(self):
        html = page(ld_block(), [episode(1)])
        record, verdict = ap._parse_record(TITLE_URL, '{"id":"abc"}', html)
        self.assertEqual(verdict, "")
        self.assertEqual(record["queue_payload"], {"id": "abc"})


if __name__ == "__main__":
    unittest.main()
