"""Offline unit tests for the HindiLinks4u staging scraper (no network)."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import import_hindilinks4u as hl


class FakeClient:
    base_url = "https://www.hindilinks4u.zip"

    def __init__(self, page: str):
        self._page = page

    def get_text(self, url, **kwargs):
        return 200, url, self._page


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


if __name__ == "__main__":
    unittest.main()
