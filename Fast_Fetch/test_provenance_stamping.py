#!/usr/bin/env python3
"""
test_provenance_stamping.py — offline regression tests for the D3/D4 provenance
and scrape-state fixes, and for restamp_provenance.py (the historical repair).

Everything runs against temporary SQLite files; no staging or production
database is touched, and nothing here merges a catalog.
"""

from __future__ import annotations

import contextlib
import io
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import import_9xmovies
import import_bolly4u
import import_desicinemas
import import_hdtvb
import import_moviezguru
import import_world4ufree
import restamp_provenance as rp

D4_IMPORTERS = (import_9xmovies, import_moviezguru, import_world4ufree, import_bolly4u)

REGISTRY_FIXTURE = {
    "sites": {
        "desicinemas": {
            "active_base_url": "https://www.desicinemas.pk",
            "known_mirrors": ["https://www.desicinemas.pk", "https://desicinemas.tv"],
        },
        "hdhub4u": {
            "active_base_url": "https://new8.hdhub4u.cl",
            "known_mirrors": ["https://hdhub4u.fans"],
        },
        "hdtvb": {
            "active_base_url": "https://hdutv.com",
            "known_mirrors": ["https://hdutv.com", "https://hdtvb.net"],
        },
    }
}


def run_quietly(func, *args, **kwargs):
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = func(*args, **kwargs)
    return result, buffer.getvalue()


class ScrapeStateMachineTests(unittest.TestCase):
    """D4: scraped=2 is retired everywhere, and legacy 2 rows are still drained."""

    def test_importers_agree_on_the_state_vocabulary(self):
        states = {module.QUEUED_SCRAPE_STATES for module in D4_IMPORTERS}
        self.assertEqual(states, {(0, 2)})
        for module in D4_IMPORTERS:
            self.assertIn("scraped IN (?, ?)", module.PENDING_SELECT)

    def test_no_importer_writes_the_retired_state_anymore(self):
        for module in D4_IMPORTERS + (import_desicinemas, import_hdtvb):
            source = Path(module.__file__).read_text(encoding="utf-8")
            self.assertNotIn("SET scraped = 2", source, module.__name__)
            self.assertNotIn("scraped=2", source, module.__name__)

    def test_skip_path_lands_on_needs_review_and_legacy_two_is_drained(self):
        for module in D4_IMPORTERS:
            with self.subTest(module=module.__name__):
                with tempfile.TemporaryDirectory() as tmp:
                    db_path = Path(tmp) / "staging.db"
                    module.init_staging_db(db_path)
                    skipped_url = "https://example.test/download/skipped/"
                    parked_url = "https://example.test/download/parked/"
                    with sqlite3.connect(str(db_path)) as conn:
                        conn.execute(
                            "INSERT INTO sitemap_cache (loc, slug, scraped) VALUES (?, ?, 0);",
                            (skipped_url, "skipped"),
                        )
                        conn.execute(
                            "INSERT INTO sitemap_cache (loc, slug, scraped) VALUES (?, ?, 2);",
                            (parked_url, "parked"),
                        )
                        conn.commit()

                    module.save_post_to_staging(db_path, {"loc": skipped_url, "skipped": True})

                    with sqlite3.connect(str(db_path)) as conn:
                        state = conn.execute(
                            "SELECT scraped FROM sitemap_cache WHERE loc = ?;", (skipped_url,)
                        ).fetchone()[0]
                        self.assertEqual(state, -1)
                        self.assertEqual(
                            conn.execute(
                                "SELECT COUNT(*) FROM sitemap_cache WHERE loc = ? AND scraped = 2;",
                                (skipped_url,),
                            ).fetchone()[0],
                            0,
                        )
                        drained = [
                            row[0]
                            for row in conn.execute(
                                module.PENDING_SELECT, module.QUEUED_SCRAPE_STATES
                            ).fetchall()
                        ]
                        self.assertIn(parked_url, drained)
                        self.assertNotIn(skipped_url, drained)


class SiteStampTests(unittest.TestCase):
    """D3/D1: each importer stamps its own site key, never a sibling's."""

    def test_hdtvb_and_hdhub4u_have_distinct_keys(self):
        self.assertEqual(import_hdtvb.SITE_KEY, "hdtvb")
        self.assertNotEqual(import_hdtvb.SITE_KEY, "hdhub4u")
        self.assertEqual(import_desicinemas.SITE, "desicinemas")

    def test_hdhub4u_literal_is_gone_from_the_hdtvb_importer(self):
        source = Path(import_hdtvb.__file__).read_text(encoding="utf-8")
        self.assertNotIn("'hdhub4u'", source)
        self.assertNotIn('"hdhub4u"', source)
        # the genuine cross-site reference is a mirror note, kept in prose only
        self.assertIn("HDHub4u catalog", source)

    def test_desicinemas_legal_media_types_match_the_engine(self):
        self.assertEqual(
            set(import_desicinemas.LEGAL_MEDIA_TYPES), set(rp.LEGAL_MEDIA_TYPES)
        )
        self.assertNotIn("episode", import_desicinemas.LEGAL_MEDIA_TYPES)

    def test_desicinemas_never_stores_illegal_media_types(self):
        for value in ("episode", "Episode", "SEASON", "anime", "", None):
            self.assertIn(
                import_desicinemas.normalize_media_type(value),
                import_desicinemas.LEGAL_MEDIA_TYPES,
            )


class RestampToolFixture(unittest.TestCase):
    """Shared temp fixture: a target catalog, one staging DB, one registry."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.staging_dir = self.tmp / "data"
        self.staging_dir.mkdir()
        self.registry = self.tmp / "domain_registry.json"
        self.registry.write_text(json.dumps(REGISTRY_FIXTURE), encoding="utf-8")

        staging = sqlite3.connect(str(self.staging_dir / "hdtvb.db"))
        staging.execute("CREATE TABLE sitemap_cache (loc TEXT PRIMARY KEY, scraped INTEGER)")
        staging.execute(
            "INSERT INTO sitemap_cache VALUES ('https://hdutv.com/movie-x.html', 1)"
        )
        staging.commit()
        staging.close()

        self.target = self.tmp / "merged_catalog.db"
        self._build_target(self.target)

    def _build_target(self, path: Path):
        conn = sqlite3.connect(str(path))
        conn.execute(
            "CREATE TABLE posts (id INTEGER PRIMARY KEY, url TEXT, slug TEXT,"
            " source_site TEXT, content_type TEXT)"
        )
        conn.executemany(
            "INSERT INTO posts (url, source_site, content_type) VALUES (?, ?, ?)",
            [
                # D1 shape: unknown, provable by host + staging URL evidence
                ("https://www.desicinemas.pk/movies/a/", "unknown", "episode"),
                # D3 shape: wrong known stamp, both evidence sources say hdtvb
                ("https://hdutv.com/movie-x.html", "hdhub4u", "movie"),
                # correctly stamped rows must never move
                ("https://new8.hdhub4u.cl/p/", "hdhub4u", "movie"),
                ("https://hdtvb.net/p.html", "hdtvb", "series"),
                # unprovable unknown stays unknown
                ("https://unmapped.example.org/x", "unknown", "movie"),
            ],
        )
        conn.execute("CREATE TABLE post_sources (post_id INTEGER, source_site TEXT, url TEXT)")
        conn.execute("INSERT INTO post_sources VALUES (3, 'hdhub4u', 'https://hdutv.com/movie-x.html')")
        conn.commit()
        conn.close()

    def build_args(self, db: Path, *extra: str) -> list[str]:
        return [
            "--db", str(db),
            "--staging-dir", str(self.staging_dir),
            "--registry", str(self.registry),
            *extra,
        ]

    def tearDown(self):
        self._tmp.cleanup()


class RestampToolTests(RestampToolFixture):
    def test_dry_run_is_the_default_and_writes_nothing(self):
        before = self.target.read_bytes()
        code, output = run_quietly(rp.main, self.build_args(self.target))
        self.assertEqual(code, 0)
        self.assertEqual(self.target.read_bytes(), before)
        self.assertIn("DRY RUN", output)
        self.assertIn("WOULD RE-STAMP", output)
        # predicted rows: posts 2 + post_sources 1 site changes, 1 media type
        self.assertIn("site rows changed : 3", output)
        self.assertIn("media rows changed: 1", output)

    def test_production_path_is_refused_without_the_flag(self):
        production = self.tmp / rp.PRODUCTION_DB_NAME
        production.write_bytes(self.target.read_bytes())
        before = production.read_bytes()
        with contextlib.redirect_stderr(io.StringIO()) as err:
            code = rp.main(self.build_args(production))
        self.assertEqual(code, 2)
        self.assertIn("REFUSED", err.getvalue())
        self.assertEqual(production.read_bytes(), before)

        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = rp.main(self.build_args(production, "--force-production"))
        self.assertEqual(code, 0)

    def test_apply_backs_up_and_is_idempotent(self):
        with contextlib.redirect_stdout(io.StringIO()):
            code = rp.main(self.build_args(self.target, "--apply"))
        self.assertEqual(code, 0)
        backups = list(self.tmp.glob("merged_catalog.db.pre-restamp-*.bak"))
        self.assertEqual(len(backups), 1)

        with sqlite3.connect(str(self.target)) as conn:
            rows = dict(conn.execute("SELECT url, source_site FROM posts").fetchall())
        self.assertEqual(rows["https://www.desicinemas.pk/movies/a/"], "desicinemas")
        self.assertEqual(rows["https://hdutv.com/movie-x.html"], "hdtvb")
        self.assertEqual(rows["https://new8.hdhub4u.cl/p/"], "hdhub4u")
        self.assertEqual(rows["https://unmapped.example.org/x"], "unknown")
        with sqlite3.connect(str(self.target)) as conn:
            self.assertEqual(
                conn.execute("SELECT source_site FROM post_sources").fetchone()[0], "hdtvb"
            )
            self.assertEqual(
                conn.execute(
                    "SELECT content_type FROM posts WHERE url = 'https://www.desicinemas.pk/movies/a/'"
                ).fetchone()[0],
                "series",
            )

        second, output = run_quietly(rp.main, self.build_args(self.target))
        self.assertEqual(second, 0)
        self.assertIn("Nothing to repair", output)
        self.assertIn("site rows changed : 0", output)
        self.assertEqual(len(list(self.tmp.glob("*.pre-restamp-*.bak"))), 1)

    def test_known_stamp_only_moves_when_both_evidence_sources_agree(self):
        host_only = self.tmp / "host_only.db"
        conn = sqlite3.connect(str(host_only))
        conn.execute(
            "CREATE TABLE posts (id INTEGER PRIMARY KEY, url TEXT, source_site TEXT, content_type TEXT)"
        )
        # hdutv.com resolves by host, but no staging DB proves this URL, so a
        # row already stamped with a site must not move.
        conn.execute(
            "INSERT INTO posts (url, source_site, content_type)"
            " VALUES ('https://hdtvb.net/only-host.html', 'multimovies', 'movie')"
        )
        conn.commit()
        conn.close()
        _code, output = run_quietly(rp.main, self.build_args(host_only))
        self.assertIn("site rows changed : 0", output)

    def test_missing_staging_dir_still_repairs_by_host_for_unknown_rows(self):
        target = self.tmp / "no_staging.db"
        target.write_bytes(self.target.read_bytes())
        _code, output = run_quietly(
            rp.main,
            ["--db", str(target), "--staging-dir", str(self.tmp / "absent"),
             "--registry", str(self.registry)],
        )
        self.assertIn("URL evidence: 0 page URLs", output)
        # only the unknown desicinemas row is provable by host alone; the
        # wrong-but-known hdhub4u stamps need staging evidence as well
        self.assertIn("site rows changed : 1", output)


if __name__ == "__main__":
    unittest.main()
