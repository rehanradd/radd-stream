"""Offline unit tests for the HindiLinks4u staging scraper (no network)."""
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import import_hindilinks4u as hl


class FakeClient:
    base_url = "https://www.hindilinks4u.zip"

    def __init__(self, page: str, code: int = 200):
        self._page = page
        self._code = code

    def get_text(self, url, **kwargs):
        return self._code, url, self._page


class StoppingClient(FakeClient):
    """Simulates the SIGTERM race: get_text returns the (0, url, "") tuple."""

    def get_text(self, url, **kwargs):
        return 0, url, ""


PAGE = """
<html><head>
<title>MobLand (2025) Season 1 Complete 1080p WEB-DL Hindi - Hindilinks4u</title>
<meta property="og:image" content="https://www.hindilinks4u.zip/poster.jpg"/>
<meta name="description" content="A family saga of the mob.";
</head><body>
<div class="entry-content">
<ul id="video_tabs">
  <li><a href="https://playmogo.com/v/abc123">Server 1 (1080p)</a></li>
  <li><a href="https://mixdrop.to/e/mdef456">Server 2</a></li>
</ul>
<p><a href="https://somehost.workers.dev/files/MobLand.2025.1080p.mkv">Download</a></p>
<p><a href="https://twitter.com/hl4u">Twitter</a></p>
</div>
<footer>done</footer>
</body></html>
"""


class TitleTests(unittest.TestCase):
    def test_clean_title_strips_qualities_and_year(self):
        clean, year, key = hl.clean_hl4u_title(
            "MobLand (2025) Season 1 Complete 1080p WEB-DL Hindi - Hindilinks4u")
        self.assertEqual(clean, "MobLand")
        self.assertEqual(year, 2025)
        self.assertTrue(key)

    def test_truncated_paren_never_leaks_into_title(self):
        for raw in (
            "MobLand (2025 Ep 01) Hindi Dubbed Season 2 - Hindilinks4u",
            "Love in Disguise (2026 Ep 01) Hindi Dubbed Season 1 romantic",
        ):
            clean, _year, _key = hl.clean_hl4u_title(raw)
            self.assertNotIn("(", clean)
            self.assertNotIn(")", clean)

    def test_no_midword_truncation(self):
        clean, _year, _key = hl.clean_hl4u_title(
            "Bigg Boss (2026 Grand Premiere) Hindi Season 20 ultimate r")
        self.assertEqual(clean, "Bigg Boss")


class ServerTests(unittest.TestCase):
    def test_tabs_and_external_mirrors(self):
        releases = hl.extract_hl4u_servers(PAGE, "https://www.hindilinks4u.zip/mobland/")
        hosts = [r["bridge_url"] for r in releases]
        self.assertIn("https://playmogo.com/v/abc123", hosts)
        self.assertIn("https://mixdrop.to/e/mdef456", hosts)
        self.assertTrue(any(r["bridge_url"].endswith(".mkv") for r in releases))
        self.assertFalse(any("twitter.com" in r["bridge_url"] for r in releases))

    def test_quality_from_label(self):
        releases = hl.extract_hl4u_servers(PAGE, "https://www.hindilinks4u.zip/mobland/")
        tab1 = next(r for r in releases if "playmogo" in r["bridge_url"])
        self.assertEqual(tab1["quality"], "1080p")


class ParseAndSaveTests(unittest.TestCase):
    def test_parse_full_page(self):
        post = hl.parse_filmy_page(FakeClient(PAGE), "https://www.hindilinks4u.zip/mobland-2025/")
        self.assertIsNotNone(post)
        self.assertEqual(post["title"], "MobLand")
        self.assertEqual(post["media_type"], "series")
        self.assertTrue(post["poster_url"].endswith("poster.jpg"))
        self.assertTrue(post["releases"])
        for r in post["releases"]:
            self.assertTrue(r["sources"])

    def test_adult_title_is_flagged_not_skipped(self):
        page = PAGE.replace("MobLand (2025)", "Hotshots (2025) 18+ Uncut")
        post = hl.parse_filmy_page(FakeClient(page), "https://www.hindilinks4u.zip/x/")
        self.assertEqual(post["is_18_plus"], 1)

    def test_save_roundtrip(self):
        post = hl.parse_filmy_page(FakeClient(PAGE), "https://www.hindilinks4u.zip/mobland-2025/")
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "hindilinks4u.db"
            hl.init_staging_db(db)
            self.assertTrue(hl.save_post_to_staging_db(db, post))
            import sqlite3
            conn = sqlite3.connect(db)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM releases").fetchone()[0], len(post["releases"]))
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0],
                             sum(len(r["sources"]) for r in post["releases"]))
            self.assertEqual(conn.execute("SELECT is_18_plus FROM posts").fetchone()[0], 0)


# ── Legacy layout and failure-cause bookkeeping ───────────────────────────────
# Recorded from live hindilinks4u.zip pages on 2026-10-23 while auditing the
# 3,673 `scraped=-1` rows: pre-`video_tabs` posts put every watch link in a
# <strong>Server N – Host</strong> block pointing at filmshowonline.net, and the
# scraper answered "failure" for them.
LEGACY_PAGE = """
<html><head><title>Sarphira (1992) Hindi - Hindilinks4u</title></head><body>
<div class="entry-content">
<p>Synopsis: a judge's household.</p>
<p style="text-align: justify"><strong>Server 1 &ndash; Youtube</strong></p>
<p style="text-align: justify"><a href="http://www.filmshowonline.net/videos/192588/">Watch Full Movie</a></p>
<p><strong>Server 2 &ndash; Dailymotion</strong></p>
<p><a href="http://www.filmshowonline.net/videos/124343/">Watch Part 1</a><br />
   <a href="http://www.filmshowonline.net/videos/124344/">Watch Part 2</a><br /></p>
<p><strong>Server 3</strong></p>
<p><a href="https://www.youtube.com/watch?v=WVVbdNpxFW0&amp;feature=player_embedded">Watch Full Movie</a></p>
<p>Click Here Desi Leaked Videos</p>
<a href="https://mydesi.cam/offer/">MyDesi</a>
<a href="https://erome.fan/x">eRomHub</a>
<p class="entry-summary">Server 1 Server 2 Server 3 Watch Some Other Post</p>
</div>
<footer>done</footer>
</body></html>
"""

SOURCELESS_PAGE = """
<html><head><title>Addicted Hindi Web Series - Hindilinks4u</title></head><body>
<div class="entry-content">
<p>Synopsis: a psychological thriller.</p>
<p>Category: Series Tags: 2021 , Crime , Series</p>
<p class="entry-summary"> Server 1 Server 2 Server 3 Watch Related Post Title</p>
</div>
<footer>done</footer>
</body></html>
"""

CHALLENGE_PAGE = """
<html><head><title>Just a moment...</title></head><body>
<form id="challenge-form"><noscript>Enable JavaScript and cookies to continue</noscript>
<div class="cf-browser-verification"></div></body></html>
"""


class LegacyLayoutTests(unittest.TestCase):
    def test_legacy_server_block_is_recovered(self):
        releases = hl.extract_hl4u_servers(LEGACY_PAGE, "https://www.hindilinks4u.zip/sarphira-1992/")
        urls = [r["bridge_url"] for r in releases]
        self.assertIn("http://www.filmshowonline.net/videos/192588/", urls)
        self.assertIn("http://www.filmshowonline.net/videos/124343/", urls)
        self.assertIn("http://www.filmshowonline.net/videos/124344/", urls)
        self.assertTrue(any("youtube.com/watch" in u for u in urls), urls)
        self.assertEqual(len(urls), len(set(urls)), "each source must appear once")

    def test_legacy_labels_are_kept(self):
        releases = hl.extract_hl4u_servers(LEGACY_PAGE, "https://www.hindilinks4u.zip/sarphira-1992/")
        labels = [r["label"] for r in releases]
        self.assertTrue(any(l.startswith("Server 1") and "Youtube" in l for l in labels), labels)
        self.assertTrue(any("Watch Part 2" in l for l in labels), labels)
        by_url = {r["bridge_url"]: r for r in releases}
        self.assertEqual(by_url["http://www.filmshowonline.net/videos/192588/"]["service"],
                         "filmshowonline")

    def test_site_wide_ad_links_are_never_sources(self):
        releases = hl.extract_hl4u_servers(LEGACY_PAGE, "https://www.hindilinks4u.zip/sarphira-1992/")
        urls = " ".join(r["bridge_url"] for r in releases)
        self.assertNotIn("mydesi", urls)
        self.assertNotIn("erome", urls)
        # The "You may also like" card text mentions servers but owns no links.
        self.assertEqual(len(releases), 4, urls)

    def test_sourceless_page_is_not_mistaken_for_legacy_layout(self):
        self.assertEqual(hl.extract_hl4u_servers(SOURCELESS_PAGE, "x"), [])

    def test_tabs_and_legacy_block_do_not_collide(self):
        page = PAGE.replace('<div class="entry-content">',
                            '<div class="entry-content"><p><strong>Server 9 – Youtube</strong></p>'
                            '<p><a href="http://www.filmshowonline.net/videos/5/">Watch Full Movie</a></p>')
        releases = hl.extract_hl4u_servers(page, "https://www.hindilinks4u.zip/mobland-2025/")
        urls = [r["bridge_url"] for r in releases]
        self.assertIn("https://playmogo.com/v/abc123", urls)
        self.assertIn("http://www.filmshowonline.net/videos/5/", urls)
        self.assertEqual(len(urls), len(set(urls)))


class CauseTests(unittest.TestCase):
    def test_ok_cause_carries_release_count(self):
        post, cause = hl.parse_filmy_page_detailed(FakeClient(LEGACY_PAGE),
                                                   "https://www.hindilinks4u.zip/sarphira-1992/")
        self.assertIsNotNone(post)
        self.assertEqual(cause["cause"], "ok")
        self.assertEqual(cause["releases"], 4)
        self.assertFalse(cause["permanent"])

    def test_wrapper_still_returns_only_the_post(self):
        self.assertIsNotNone(hl.parse_filmy_page(FakeClient(PAGE),
                                                 "https://www.hindilinks4u.zip/mobland-2025/"))

    def test_404_is_a_permanent_dead_page(self):
        post, cause = hl.parse_filmy_page_detailed(FakeClient("", code=404),
                                                   "https://www.hindilinks4u.zip/gone/")
        self.assertIsNone(post)
        self.assertEqual(cause["cause"], "http_404_gone")
        self.assertTrue(cause["permanent"])

    def test_429_is_retryable_our_own_rate(self):
        self.assertEqual(hl._http_cause(429), "http_429_rate_limited")
        self.assertNotIn("http_429_rate_limited", hl.PERMANENT_CAUSES)

    def test_transport_error_is_retryable(self):
        post, cause = hl.parse_filmy_page_detailed(StoppingClient(""),
                                                   "https://www.hindilinks4u.zip/x/")
        self.assertIsNone(post)
        self.assertEqual(cause["cause"], "transport_error")
        self.assertFalse(cause["permanent"])

    def test_challenge_is_recorded_and_not_bypassed(self):
        post, cause = hl.parse_filmy_page_detailed(FakeClient(CHALLENGE_PAGE),
                                                   "https://www.hindilinks4u.zip/x/")
        self.assertIsNone(post)
        self.assertEqual(cause["cause"], "blocked: challenge")
        self.assertTrue(cause["permanent"])
        self.assertTrue(hl.looks_blocked(CHALLENGE_PAGE))
        self.assertFalse(hl.looks_blocked(PAGE))

    def test_sourceless_page_is_permanent_not_a_scrape_error(self):
        post, cause = hl.parse_filmy_page_detailed(FakeClient(SOURCELESS_PAGE),
                                                   "https://www.hindilinks4u.zip/addicted/")
        self.assertIsNone(post)
        self.assertEqual(cause["cause"], "no_sources_on_page")
        self.assertTrue(cause["permanent"])
        self.assertIn("Addicted", cause["raw_title"])

    def test_non_post_urls_are_skipped_without_a_request(self):
        class ExplodingClient:
            base_url = hl.DEFAULT_BASE_URL

            def get_text(self, *a, **k):
                raise AssertionError("must not fetch a taxonomy page")

        for loc in ("https://www.hindilinks4u.zip/",
                    "https://www.hindilinks4u.zip/category/hindi-movies/"):
            post, cause = hl.parse_filmy_page_detailed(ExplodingClient(), loc)
            self.assertIsNone(post)
            self.assertEqual(cause["cause"], "skipped: not_a_post")
        self.assertTrue(hl.is_post_url("https://www.hindilinks4u.zip/sikandar-2025-hindi/"))


class CauseBookkeepingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "hindilinks4u.db"
        hl.init_staging_db(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def _set_state(self, loc, scraped, raw=None):
        with sqlite3.connect(self.db) as con:
            con.execute("INSERT INTO sitemap_cache (loc, slug, scraped, raw_json) VALUES (?,?,?,?)",
                        (loc, loc.rstrip('/').split('/')[-1], scraped, raw))
            con.commit()

    def test_record_cause_stores_json_and_state(self):
        self._set_state("https://www.hindilinks4u.zip/boom/", 0)
        hl.record_cause(self.db, "https://www.hindilinks4u.zip/boom/", -1,
                        hl._cause("http_429_rate_limited", http=429))
        with sqlite3.connect(self.db) as con:
            scraped, raw = con.execute(
                "SELECT scraped, raw_json FROM sitemap_cache WHERE loc=?",
                ("https://www.hindilinks4u.zip/boom/",)).fetchone()
        self.assertEqual(scraped, -1)
        self.assertEqual(json.loads(raw)["cause"], "http_429_rate_limited")
        self.assertEqual(hl.cause_breakdown(self.db), {"http_429_rate_limited": 1})

    def test_success_clears_the_stale_failure_note(self):
        self._set_state("https://www.hindilinks4u.zip/healed/", -1,
                        json.dumps(hl._cause("no_sources_on_page")))
        self.assertEqual(hl.cause_breakdown(self.db), {"no_sources_on_page": 1})
        hl.record_cause(self.db, "https://www.hindilinks4u.zip/healed/", 1, None)
        with sqlite3.connect(self.db) as con:
            scraped, raw = con.execute(
                "SELECT scraped, raw_json FROM sitemap_cache WHERE loc=?",
                ("https://www.hindilinks4u.zip/healed/",)).fetchone()
        self.assertEqual((scraped, raw), (1, None))
        self.assertEqual(hl.cause_breakdown(self.db), {})

    def test_pre_bookkeeping_rows_are_reported_as_unrecorded(self):
        self._set_state("https://www.hindilinks4u.zip/old-failure/", -1)
        self.assertEqual(hl.cause_breakdown(self.db), {"unrecorded": 1})


if __name__ == "__main__":
    unittest.main()
