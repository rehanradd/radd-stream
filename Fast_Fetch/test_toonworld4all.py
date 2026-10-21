"""Offline unit tests for the ToonWorld4All staging scraper (no network)."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

sys_path = Path(__file__).parent
import sys

sys.path.insert(0, str(sys_path))
import import_toonworld4all as tw

EPISODE_URL = "https://archive.toonworld4all.me/episode/doraemon-2-14/"

EP_DATA = {
    "metadata": {"show": "Doraemon", "season": 2, "episode": 14, "air": "2024-01-05",
                 "overview": "Nobita invents trouble.", "poster": "https://p/1.jpg"},
    "encodes": [
        {"resolution": "1080p", "codec": "x265", "bit_depth": 10, "size": 3_000_000_000,
         "readable": {"codec": "HEVC 10bit"},
         "files": [{"host": "HubCloud", "short": "hc", "link": "/redirect/abc1"}]},
        {"resolution": "480p", "codec": "x264", "size": 500_000_000,
         "readable": {"codec": "x264"},
         "files": [{"host": "FilePress", "short": "new4.filepress.baby",
                    "link": "https://new4.filepress.baby/f/zz9"}]},
    ],
    "streams": [{"host": "ToonPlayer", "link": "https://archive.toonworld4all.me/stream/qq/"}],
}

REDIRECT_PAGE = (
    '<script>window.__PROPS__={"destination":"https://fallback/",'
    '"link":{"domain":"https://hubcloud.ist/video/","hidden":"uge9ux2abqynbqv"}};</script>'
    "<script>window.foo=1;</script>"
)


class FakeClient:
    base_url = "https://toonworld4all.me"

    def get_text(self, url, **kwargs):
        if "/redirect/" in url:
            return 200, url, REDIRECT_PAGE
        return 404, url, ""


class PropsTests(unittest.TestCase):
    def test_page_props_json(self):
        props = tw._page_props(REDIRECT_PAGE)
        self.assertEqual(props["link"]["hidden"], "uge9ux2abqynbqv")

    def test_page_props_missing(self):
        self.assertIsNone(tw._page_props("<html>no props</html>"))

    def test_episode_href_relative_and_absolute(self):
        html = ('<a href="/episode/shinzo-314/">S</a>'
                '<a class="x" href="https://archive.toonworld4all.me/episode/a-1/">T</a>')
        found = [(m.group(1), m.group(2)) for m in tw.EPISODE_HREF_RE.finditer(html)]
        self.assertEqual(len(found), 2)
        abs_urls = [(pre or "https://archive.toonworld4all.me") + href for pre, href in found]
        self.assertIn("https://archive.toonworld4all.me/episode/shinzo-314/", abs_urls)


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.result = tw.build_episode_release(FakeClient(), EPISODE_URL, EP_DATA, True)
        self.releases = self.result["releases"]

    def test_one_release_per_encode(self):
        self.assertEqual(len(self.releases), 2)
        self.assertEqual({r["quality"] for r in self.releases}, {"1080p", "480p"})

    def test_sources_are_scoped_to_their_quality(self):
        hd = next(r for r in self.releases if r["quality"] == "1080p")
        sd = next(r for r in self.releases if r["quality"] == "480p")
        hd_mirrors = [s for s in hd["sources"] if s["service"] != "stream"]
        self.assertTrue(all(s["quality"] == "1080p" for s in hd_mirrors))
        self.assertTrue(all(s["quality"] == "480p" for s in sd["sources"]))
        self.assertEqual(len(hd_mirrors), 1)

    def test_redirect_unwrapped_to_final_cdn(self):
        hd = self.releases[0]
        mirror = next(s for s in hd["sources"] if s["service"] == "hc")
        self.assertEqual(mirror["final_url"], "https://hubcloud.ist/video/uge9ux2abqynbqv")
        self.assertEqual(mirror["source_url"], "https://archive.toonworld4all.me/redirect/abc1")

    def test_second_level_service_label(self):
        sd = next(r for r in self.releases if r["quality"] == "480p")
        mirror = next(s for s in sd["sources"] if "filepress" in s["source_url"])
        self.assertEqual(mirror["service"], "filepress")

    def test_stream_sources_recorded_once(self):
        streams = [s for r in self.releases for s in r["sources"] if s["service"] == "stream"]
        self.assertEqual(len(streams), 1)

    def test_codec_and_label(self):
        hd = next(r for r in self.releases if r["quality"] == "1080p")
        self.assertEqual(hd["codec"], "HEVC")
        self.assertEqual(hd["season_number"], 2)
        self.assertEqual(hd["episode_number"], 14)
        self.assertIn("S02E14", hd["label"])
        self.assertEqual(hd["size_bytes"], 3_000_000_000)

    def test_stream_only_episode_still_stores_sources(self):
        data = {"metadata": {"show": "Shinzo", "season": 1, "episode": 3},
                "encodes": [], "streams": [{"host": "Player", "link": "https://archive.toonworld4all.me/stream/zz/"}]}
        res = tw.build_episode_release(FakeClient(), "https://archive.toonworld4all.me/episode/shinzo-1-3/", data, False)
        self.assertEqual(len(res["releases"]), 1)
        self.assertEqual(len(res["releases"][0]["sources"]), 1)

    def test_empty_episode_returns_none(self):
        self.assertIsNone(tw.build_episode_release(
            FakeClient(), EPISODE_URL, {"metadata": {}, "encodes": [], "streams": []}, False))


class SaveTests(unittest.TestCase):
    def test_save_releases_and_sources(self):
        post = {
            "canonical_key": "doraemon_2024_s02",
            "title": "Doraemon",
            "original_title": "Doraemon",
            "year": 2024,
            "media_type": "series",
            "imdb_id": None,
            "poster_url": "https://p/1.jpg",
            "genres": json.dumps(["Comedy"]),
            "director": None,
            "cast_names": None,
            "synopsis": "Nobita invents trouble.",
            "languages": json.dumps(["Hindi"]),
            "is_18_plus": 0,
            "site": "toonworld4all",
            "post_url": EPISODE_URL,
            "releases": tw.build_episode_release(FakeClient(), EPISODE_URL, EP_DATA, True)["releases"],
        }
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "toonworld4all.db"
            tw.init_staging_db(db)
            self.assertTrue(tw.save_post_to_staging_db(db, post))
            conn = sqlite3.connect(db)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM releases").fetchone()[0], 2)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0], 3)
            adult = dict(post, canonical_key="adult_show_s01", title="Uncut Erotic Show", is_18_plus=1)
            tw.save_post_to_staging_db(db, adult)
            self.assertEqual(conn.execute(
                "SELECT is_18_plus FROM posts WHERE canonical_key='adult_show_s01'").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
