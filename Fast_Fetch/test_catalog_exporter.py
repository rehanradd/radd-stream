#!/usr/bin/env python3
"""
test_catalog_exporter.py — proves the static export is safe by construction.

The Crown Prince order (qoder13) demands assertions on the EMITTED BYTES, not
on column values: a static JSON has no runtime gate, so the only honest test
is "search the artifact and show the flagged work is not there".

Offline and stdlib-only: a fixture database in a temp directory, an export to
a temp staging dir, byte assertions. No network, no nginx, no /var/www.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import catalog_exporter  # noqa: E402


# Distinctive ids so a digit substring cannot collide with a count or a year.
ADULT_POST_ID = 9107001        # flagged row itself
TWIN_POST_ID = 9107002         # unflagged twin sharing the canonical_key — the leak
CLEAN_POST_ID = 9107003
ADULT_TITLE = "Operation Flagged XxX"
TWIN_TITLE = "Forbidden Desert Rumble"   # the same work, unflagged row, must vanish
SCRAPE_SITE_ART = "https://sexdvemovies.example/uploads/poster-9107003.jpg"
TMDB_ART = "https://image.tmdb.org/t/p/w500/abc123.jpg"


class _Fixture(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="exporter-test-")
        self.addCleanup(self._tmp.cleanup)
        self.db = str(Path(self._tmp.name) / "fixture.db")
        self.stage = str(Path(self._tmp.name) / "stage")
        self._make_db()

    def _make_db(self) -> None:
        conn = sqlite3.connect(self.db)
        conn.executescript("""
            CREATE TABLE posts (
                id INTEGER PRIMARY KEY, url TEXT, slug TEXT, title TEXT,
                clean_title TEXT, year TEXT, content_type TEXT, seasons TEXT,
                poster_url TEXT, backdrop_urls TEXT, imdb_rating TEXT,
                synopsis TEXT, is_18_plus INTEGER, is_animated INTEGER,
                genres TEXT,
                lastmod TEXT, created_at TEXT, updated_at TEXT,
                source_site TEXT, industry TEXT, country TEXT, language TEXT,
                canonical_key TEXT, tmdb_id TEXT, imdb_id TEXT);
            CREATE TABLE releases (id INTEGER PRIMARY KEY, post_id INTEGER,
                release_title TEXT, season TEXT, episode TEXT, quality TEXT,
                codec TEXT, size TEXT, languages TEXT, intermediate_url TEXT,
                source_site TEXT, origin_url TEXT, created_at TEXT);
            CREATE TABLE download_sources (id INTEGER PRIMARY KEY,
                release_id INTEGER, source_name TEXT, service TEXT,
                resource_id TEXT, source_url TEXT, final_url TEXT,
                playback_type TEXT, is_temporary INTEGER, status TEXT,
                is_resumable INTEGER, http_status INTEGER,
                file_size_bytes INTEGER, mime_type TEXT, last_checked_at TEXT,
                created_at TEXT, updated_at TEXT);
        """)
        rows = [
            # (id, title, is_18_plus, canonical_key, poster, backdrops)
            (ADULT_POST_ID, ADULT_TITLE, 1, "work:forbidden-desert", TMDB_ART,
             [TMDB_ART]),
            (TWIN_POST_ID, TWIN_TITLE, 0, "work:forbidden-desert", TMDB_ART,
             [TMDB_ART]),
            # Visible row mixes both art kinds: the public CDN URL must be kept,
            # the scraped site's own image path must be dropped.
            (CLEAN_POST_ID, "A Totally Normal Documentary", 0, "work:normal-doc",
             TMDB_ART, [TMDB_ART, SCRAPE_SITE_ART]),
        ]
        for pid, title, flag, key, art, decks in rows:
            conn.execute(
                "INSERT INTO posts (id, title, clean_title, year, content_type,"
                " is_18_plus, canonical_key, poster_url, backdrop_urls,"
                " created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (pid, title, title, "2024", "movie", flag, key, art,
                 json.dumps(decks), "2024-01-01 00:00:00"))
            rel = conn.execute("INSERT INTO releases (post_id, release_title,"
                               " quality) VALUES (?,?,?)",
                               (pid, title + " 1080p", "1080p")).lastrowid
            conn.execute(
                "INSERT INTO download_sources (release_id, source_name, service,"
                " source_url, final_url, playback_type, status)"
                " VALUES (?,?,?,?,?,?,?)",
                (rel, "x", "pixeldrain", "https://p.example/1",
                 f"https://p.example/stream-{pid}.mp4", "direct", "active"))
        conn.commit()
        conn.close()

    def _export(self) -> dict:
        return catalog_exporter.export_catalog(self.db, self.stage, pages=3,
                                               per_page=10, verbose=False)

    def _all_bytes(self) -> str:
        blob = []
        root = Path(self.stage)
        for f in sorted(root.rglob("*.json")):
            blob.append(f.read_text(encoding="utf-8"))
        return "\n".join(blob)


class TestAdultSuppression(_Fixture):
    def test_flagged_row_absent_from_emitted_bytes(self):
        self._export()
        blob = self._all_bytes()
        self.assertNotIn(ADULT_TITLE, blob)
        self.assertNotIn(str(ADULT_POST_ID), blob)

    def test_unflagged_twin_absent_everywhere(self):
        """THE gate: today's API leak row must appear nowhere — home, browse,
        or any embedded id. Asserted on the artifact bytes per qoder13."""
        manifest = self._export()
        blob = self._all_bytes()
        self.assertNotIn(TWIN_TITLE, blob)
        self.assertNotIn(str(TWIN_POST_ID), blob)
        for f in Path(self.stage).rglob("*.json"):
            if f.name == "manifest.json":
                continue
            data = json.loads(f.read_text(encoding="utf-8"))
            ids = {r["id"] for r in data["results"]}
            self.assertNotIn(TWIN_POST_ID, ids, f"twin leaked in {f}")

    def test_clean_work_survives_and_reports_exact_suppression_count(self):
        manifest = self._export()
        blob = self._all_bytes()
        self.assertIn("A Totally Normal Documentary", blob)
        # Suppressed works = 1 (the twin key); the flagged row itself is the
        # adult_clause's job and is not double-counted.
        self.assertEqual(
            1, manifest["works_suppressed_by_canonical_key_clause"])

    def test_suppression_count_matches_live_product(self):
        """The reported number equals what the WHERE actually removed."""
        self._export()
        conn = sqlite3.connect(f"file:{self.db}?mode=ro", uri=True)
        visible = conn.execute(
            f"SELECT id FROM posts p WHERE {catalog_exporter.guarded_posts_where()}"
        ).fetchall()
        conn.close()
        self.assertEqual([CLEAN_POST_ID], [r[0] for r in visible])


class TestNoCredentialsInFiles(_Fixture):
    def test_no_signed_art_or_tokens_anywhere(self):
        self._export()
        blob = self._all_bytes()
        self.assertNotIn("/api/v1/art?id=", blob)      # signed art handle
        self.assertNotIn("/api/v1/stream", blob)       # resolve/play redirect
        self.assertNotIn("/api/v1/download", blob)     # download redirect
        self.assertNotIn("expires_in", blob)           # token lifetime fields
        self.assertNotIn("token", blob.lower())

    def test_scraped_site_art_dropped_public_cdn_art_kept(self):
        self._export()
        blob = self._all_bytes()
        self.assertNotIn("sexdvemovies.example", blob)  # would name our upstream
        self.assertIn(TMDB_ART, blob)                    # already a public CDN URL


class TestAtomicDeterministic(_Fixture):
    def test_double_export_is_byte_identical(self):
        self._export()
        first = self._all_bytes()
        self._export()
        self.assertEqual(first, self._all_bytes())

    def test_no_temp_files_left_behind(self):
        self._export()
        strays = [f for f in Path(self.stage).rglob("*")
                  if f.name.startswith(".") or f.suffix == ".tmp"]
        self.assertEqual([], strays)

    def test_pages_are_valid_json_with_full_ordered_coverage(self):
        manifest = self._export()
        self.assertTrue(Path(manifest["files"][0]).exists())
        home = json.loads((Path(self.stage) / "home.json").read_text(encoding="utf-8"))
        self.assertEqual(home["total"], 1)               # only the clean work
        self.assertEqual(len(home["results"]), 1)


class TestRefusesProductionRoot(_Fixture):
    def test_var_www_output_rejected_by_cli(self):
        with self.assertRaises(SystemExit):
            catalog_exporter.main(["--db", self.db, "--out", "/var/www/radd-static"])


class TestProjectionSemantics(unittest.TestCase):
    """Order LANE-3 §1: make `redact.project`'s drop-vs-raise behaviour explicit.

    Silent DROPPING of an off-view key is acceptable; silent KEEPING is not.
    An unpublished view name raises rather than answering with everything.
    """

    def test_off_view_keys_are_dropped_not_kept(self):
        import redact
        row = {"id": 1, "title": "Fine", "clean_title": "Fine", "year": "2024",
               "source_site": "vegamovies", "url": "https://vegamovies.tld/p/1",
               "slug": "taken-from-vegamovies", "final_url": "https://hoster/x",
               "origin_url": "https://upstream", "intermediate_url": "x"}
        out = redact.project(row, "post_brief")
        self.assertIn("title", out)
        for leak in ("source_site", "url", "slug", "final_url", "origin_url",
                     "intermediate_url"):
            self.assertNotIn(leak, out, f"projection KEPT private column {leak}")

    def test_unpublished_view_raises_instead_of_passthrough(self):
        import redact
        with self.assertRaises(redact.ProjectionError):
            redact.project({"id": 1, "source_site": "x"}, "post_everything")

    def test_export_tree_contains_no_provenance_key(self):
        import redact
        tmp = tempfile.TemporaryDirectory(prefix="exporter-proof-")
        self.addCleanup(tmp.cleanup)
        db = str(Path(tmp.name) / "d.db")
        conn = sqlite3.connect(db)
        TestProjectionSemantics._schema(conn)
        conn.execute("INSERT INTO posts (id, title, clean_title, is_18_plus,"
                     " source_site, canonical_key) VALUES (9001,'A','A',0,"
                     "'vegamovies','w1')")
        conn.commit(); conn.close()
        catalog_exporter.export_catalog(db, str(Path(tmp.name) / "s"),
                                        pages=1, per_page=5, verbose=False)
        for f in Path(tmp.name).rglob("browse/trending/*.json"):
            tree = json.loads(f.read_text(encoding="utf-8"))
            self.assertEqual([], redact.provenance_keys(tree),
                             f"{f}: provenance key present in export bytes")
            for item in tree["results"]:
                allowed = set(redact.VIEWS["post_brief"]) | {"poster_url",
                                                             "backdrop_urls"}
                extra = set(item) - allowed
                self.assertEqual(set(), extra,
                                 f"{f}: un-projected column {extra} reached output")

    @staticmethod
    def _schema(conn):
        conn.executescript("""
            CREATE TABLE posts (id INTEGER PRIMARY KEY, url TEXT, slug TEXT,
                title TEXT, clean_title TEXT, year TEXT, content_type TEXT,
                seasons TEXT, poster_url TEXT, backdrop_urls TEXT,
                imdb_rating TEXT, synopsis TEXT, is_18_plus INTEGER,
                is_animated INTEGER, genres TEXT, lastmod TEXT, created_at TEXT,
                updated_at TEXT, source_site TEXT, industry TEXT, country TEXT,
                language TEXT, canonical_key TEXT, tmdb_id TEXT, imdb_id TEXT);
            CREATE TABLE releases (id INTEGER PRIMARY KEY, post_id INTEGER,
                release_title TEXT, season TEXT, episode TEXT, quality TEXT,
                codec TEXT, size TEXT, languages TEXT, intermediate_url TEXT,
                source_site TEXT, origin_url TEXT, created_at TEXT);
            CREATE TABLE download_sources (id INTEGER PRIMARY KEY,
                release_id INTEGER, source_name TEXT, service TEXT,
                resource_id TEXT, source_url TEXT, final_url TEXT,
                playback_type TEXT, is_temporary INTEGER, status TEXT,
                is_resumable INTEGER, http_status INTEGER, file_size_bytes INTEGER,
                mime_type TEXT, last_checked_at TEXT, created_at TEXT,
                updated_at TEXT);
        """)


class TestArtGuardAdversarial(_Fixture):
    """Order LANE-3 §2: audit the CDN allowlist adversarially — direct cases and
    the exporter end-to-end with a planted userinfo URL that passes the naive
    host scan (`https://scraper.tld@image.tmdb.org/…`)."""

    def test_direct_guard_cases(self):
        import redact
        allowed = ["https://m.media-amazon.com/images/I/x.jpg",
                   "https://image.tmdb.org/t/p/w500/x.jpg"]
        refused = ["https://vegamovies.tld/wp-content/uploads/x.jpg",
                   "https://image.tmdb.org.evil.tld/x.jpg",
                   "https://vegamovies.tld@image.tmdb.org/x.jpg",
                   "https://x@image.tmdb.org@vegamovies.tld/y.jpg",
                   "https://tmdb.org/x.jpg"]  # lookalike without the `image.` host
        for url in allowed:
            self.assertEqual(url, redact.public_image_value(url),
                             f"allowed CDN refused: {url}")
        for url in refused:
            self.assertIsNone(redact.public_image_value(url),
                              f"non-CDN host ACCEPTED: {url}")

    def test_planted_userinfo_art_never_reaches_export_bytes(self):
        conn = sqlite3.connect(self.db)
        conn.execute("UPDATE posts SET poster_url = ? WHERE id = ?",
                     ("https://vegamovies.tld@image.tmdb.org/t/p/x.jpg",
                      CLEAN_POST_ID))
        conn.commit(); conn.close()
        self._export()
        blob = self._all_bytes()
        self.assertNotIn("vegamovies.tld", blob)
        self.assertNotIn("vegamovies.tld@image.tmdb.org", blob)

    def test_scraper_prose_synopsis_stays_out_of_the_export(self):
        """The sweep caught 'G-Direct'/'PikaHD' inside a stored synopsis: the
        curated scrubber cannot delete unknown brands, so the export simply
        never selects the column — asserted here on planted bytes."""
        conn = sqlite3.connect(self.db)
        conn.execute("UPDATE posts SET synopsis = ? WHERE id = ?",
                     ("Watch Online G-Directs Xxxtreme PikaHD Links | " +
                      "A Totally Normal Documentary 2024 1080p", CLEAN_POST_ID))
        conn.commit(); conn.close()
        self._export()
        blob = self._all_bytes()
        self.assertNotIn("G-Directs Xxxtreme", blob)
        self.assertNotIn("PikaHD", blob)
        self.assertIn("A Totally Normal Documentary", blob)  # row still exported


if __name__ == "__main__":
    unittest.main(verbosity=2)
