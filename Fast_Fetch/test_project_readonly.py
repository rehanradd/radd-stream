#!/usr/bin/env python3
"""`project_readonly.py` rebuilds the v2 catalog and never writes to the ledger.

The production catalog is 6.4 GB and is the file the live service reads. A
rebuild that opened it read-write (as `catalog_v2.project_db` does) would write
`cat_*` into it. The driver instead ATTACHes it `mode=ro` behind TEMP VIEWs, and
these tests hold that promise at the bytes: the source's sha256 is identical
before and after, and the source gains no `cat_` table.

They also hold the acceptance bar — every ledger link is walked (the default
file's own projector counter) and every link that survives keeps a pointer back
to the row it came from.

    python3 -S Fast_Fetch/test_project_readonly.py
"""
import contextlib
import hashlib
import io
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fast_fetch       # noqa: E402
import project_readonly  # noqa: E402


def _hash(path):
    digest = hashlib.sha256()
    for name in (path, Path(str(path) + "-wal")):
        if not Path(name).exists():
            continue
        with open(name, "rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                digest.update(block)
    return digest.hexdigest()


def _media(site, slug, *, title, adult=0):
    return {
        "url": f"https://{site}.example/{slug}/",
        "slug": slug,
        "title": title,
        "clean_title": title,
        "year": 2024,
        "content_type": "movie",
        "seasons": None,
        "poster_url": None,
        "backdrop_urls": None,
        "imdb_rating": None,
        "genres": None,
        "synopsis": None,
        "is_18_plus": adult,
        "is_animated": 0,
        "source_site": site,
        "industry": "Hollywood",
        "country": "USA",
        "language": "English",
        "canonical_key": fast_fetch.generate_canonical_key(title, 2024),
        "tmdb_id": None,
        "imdb_id": None,
        "releases": [{
            "release_title": f"{title} 1080p",
            "quality": "1080p",
            "codec": "x264",
            "size": "1GB",
            "languages": "English",
            "season": None,
            "episode": None,
            "intermediate_url": f"https://{site}.example/release",
            "sources": [{
                "source_name": "Example CDN",
                "service": "test-service",
                "resource_id": f"{site}-id",
                "source_url": f"https://cdn.example/{site}/{slug}",
                "final_url": f"https://cdn.example/{site}/{slug}",
                "is_temporary": 0,
            }],
        }],
    }


class ProjectReadonlyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.src = Path(cls.tmp.name) / "ledger.db"
        patcher = mock.patch.object(fast_fetch, "DB_PATH", cls.src)
        patcher.start()
        cls.addClassCleanup(patcher.stop)
        cinemeta = mock.patch.object(fast_fetch, "fetch_cinemeta_metadata",
                                     return_value=None)
        cinemeta.start()
        cls.addClassCleanup(cinemeta.stop)
        fast_fetch.init_db()
        for site, slug, title, adult in (
            ("site_a", "example-film", "Example Film", 0),
            ("site_b", "example-film-alt", "Example Film", 0),
            ("site_c", "other-film", "Other Film", 1),
        ):
            fast_fetch.save_scraped_data(_media(site, slug, title=title, adult=adult))
        cls.before = _hash(cls.src)

    def setUp(self):
        self.out = Path(self.tmp.name) / f"{self._testMethodName}.db"

    def run_driver(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            rc = project_readonly.main(["project_readonly.py", str(self.src), str(self.out)])
        self.assertEqual(rc, 0, out.getvalue())
        return out.getvalue()

    def rows(self, db, query, params=()):
        conn = sqlite3.connect(str(db))
        try:
            return conn.execute(query, params).fetchall()
        finally:
            conn.close()

    def test_the_ledger_is_not_written(self):
        self.run_driver()
        self.assertEqual(_hash(self.src), self.before,
                         "the source database changed bytes during a rebuild")
        self.assertEqual(
            self.rows(self.src, "SELECT COUNT(*) FROM sqlite_master"
                                " WHERE type='table' AND name LIKE 'cat\\_%' ESCAPE '\\'")[0][0],
            0, "the projection created catalog tables in the ledger")

    def test_every_link_is_carried_or_its_url_survives(self):
        self.run_driver()
        sources = self.rows(self.src, "SELECT COUNT(*) FROM download_sources")[0][0]
        links = self.rows(self.out, "SELECT COUNT(*) FROM cat_links")[0][0]
        self.assertEqual(links, sources, "a link was dropped")
        orphans = self.rows(
            self.out,
            "SELECT COUNT(*) FROM cat_links l WHERE l.ledger_link_id IS NULL")[0][0]
        self.assertEqual(orphans, 0, "a projected link lost its ledger id")

    def test_the_stamp_names_the_ledger_it_read(self):
        self.run_driver()
        meta = dict(self.rows(self.out, "SELECT key, value FROM cat_projection_meta"))
        posts = self.rows(self.src, "SELECT COUNT(*) FROM posts")[0][0]
        self.assertEqual(meta["posts"], str(posts))
        self.assertEqual(meta["works"], "2", "two titles, mirrored or not, are two works")
        self.assertEqual(meta["adult_works"], "1")
        self.assertEqual(meta["works_safe"], "1")
        self.assertIn("projected_at", meta)
        # The keys `/api/v1/stats` needs to stop counting; the production file is
        # missing exactly these and falls back to a 42 s scan every cache miss.
        for key in ("links_safe", "links_resumable_safe", "links_temporary_safe",
                    "links_by_state_safe"):
            self.assertIn(key, meta)

    def test_an_existing_output_is_refused(self):
        self.run_driver()
        digest = _hash(self.out)
        with contextlib.redirect_stderr(io.StringIO()):
            rc = project_readonly.main(["project_readonly.py", str(self.src), str(self.out)])
        self.assertEqual(rc, 2)
        self.assertEqual(_hash(self.out), digest, "an existing projection was overwritten")

    def test_projecting_onto_the_source_is_refused(self):
        with contextlib.redirect_stderr(io.StringIO()):
            rc = project_readonly.main(["project_readonly.py", str(self.src), str(self.src)])
        self.assertEqual(rc, 2)
        self.assertEqual(_hash(self.src), self.before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
