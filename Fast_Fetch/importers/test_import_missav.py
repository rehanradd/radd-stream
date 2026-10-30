#!/usr/bin/env python3
"""Offline tests for import_missav.py. No network, no fixture files, no catalog.

The site is behind a Cloudflare JS challenge for unauthenticated automated
clients (measured 2026-10-30, `docs/SITE_MISSAV.md` §1), so there is no captured
page to parse and these tests do not pretend otherwise. What they do prove is
the half that must be right before any byte is fetched:

  * every row is 18+ by source, and the SCHEMA refuses an unflagged row;
  * the content code is the key, namespaced so it cannot twin with a clean row;
  * every declared tier is a release, a URL-less tier gets no source, and a
    dead mirror is stored dead rather than dropped;
  * subtitle-language tags survive verbatim;
  * the box gate refuses load/mem/another-crawler/unbounded, and `sync` refuses
    the site as well, with a different exit code;
  * nothing here invents a URL, and nothing names the production catalog.

Run: python3 -S Fast_Fetch/importers/test_import_missav.py
"""

from __future__ import annotations

import ast
import json
import re
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import import_missav as mm  # noqa: E402


def record(**over):
    base = {
        "code": "STARS-123",
        "title": "A title with no adult wording at all",
        "url": "https://missav.live/example/STARS-123",
        "studio": "Example Label",
        "release_date": "2026-02-03",
        "duration": "118 min",
        "series": "The Series",
        "performers": ["Performer One", "Performer Two"],
        "tags": ["Drama", "English subtitles"],
        "subtitles": ["English subtitles"],
        "poster_url": "https://cdn.invalid/p.jpg",
        "thumb_url": "https://cdn.invalid/t.jpg",
        "backdrop_url": "https://cdn.invalid/b.jpg",
        "streams": [
            {"quality": "1080p", "url": "https://cdn.invalid/a.m3u8"},
            {"quality": "720p", "url": "https://cdn.invalid/b.m3u8"},
        ],
        "downloads": [
            {"quality": "1080p", "url": "https://cdn.invalid/d.mp4", "status": "dead"},
            {"quality": "480p"},
        ],
    }
    base.update(over)
    return base


class DbCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "missav.db"
        self.conn = sqlite3.connect(self.db)
        self.addCleanup(self.conn.close)
        mm.ensure_schema(self.conn)

    def rows(self, sql, *args):
        return self.conn.execute(sql, args).fetchall()


class AdultBySourceTests(DbCase):
    """Rule 1: flagged unconditionally, enforced where it cannot be forgotten."""

    def test_an_unlabelled_title_still_lands_flagged(self):
        got = mm.write_record(self.conn, record())
        self.assertEqual(got["post"], 1)
        flag = self.rows("SELECT is_18_plus FROM posts WHERE canonical_key=?",
                         "missav-stars-123")[0][0]
        self.assertEqual(flag, 1, "the flag comes from the source, not the title")

    def test_the_schema_rejects_an_unflagged_insert(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO posts (canonical_key, title, clean_title, is_18_plus) "
                "VALUES ('x', 'x', 'x', 0)")

    def test_the_default_is_the_flag(self):
        self.conn.execute(
            "INSERT INTO posts (canonical_key, title, clean_title) VALUES ('y', 'y', 'y')")
        self.assertEqual(self.rows("SELECT is_18_plus FROM posts WHERE canonical_key='y'")[0][0], 1)

    def test_the_schema_rejects_another_source_site(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO posts (canonical_key, title, clean_title, source_site) "
                "VALUES ('z', 'z', 'z', 'fzmovies')")

    def test_write_record_never_reads_a_flag_from_the_input(self):
        got = mm.write_record(self.conn, record(is_18_plus=0))
        self.assertEqual(got["post"], 1)
        self.assertEqual(self.rows("SELECT is_18_plus FROM posts")[0][0], 1)


class ContentCodeTests(unittest.TestCase):
    """Rule 3's precondition: identity is the code, and it cannot twin."""

    def test_the_owner_example_becomes_the_key(self):
        self.assertEqual(mm.canonical_key("ABC-123"), "missav-abc-123")

    def test_separator_variants_normalize(self):
        for spelling in ("STARS-123", "stars-123", "Stars_123", "STARS 123", "stars123"):
            self.assertEqual(mm.canonical_key(spelling), "missav-stars-123", spelling)

    def test_a_suffix_is_kept(self):
        self.assertEqual(mm.canonical_key("ABC-123-v2"), "missav-abc-123-v2")

    def test_a_non_code_is_refused(self):
        for bad in ("", None, "Some Title 2026", "123", "A-1", "ABCDEFGHIJK-123",
                    "ABC-123456", "ABC-12-34-56"):
            with self.assertRaises(mm.RecordRefused, msg=repr(bad)):
                mm.canonical_key(bad)

    def test_the_key_is_namespaced_and_never_a_bare_slug(self):
        key = mm.canonical_key("ABC-123")
        self.assertTrue(key.startswith(mm.KEY_PREFIX))
        self.assertNotEqual(key, "abc-123")

    def test_two_titles_with_one_code_share_one_key(self):
        a = mm.normalize_record(record(title="First title"))
        b = mm.normalize_record(record(title="A completely different title"))
        self.assertEqual(a["canonical_key"], b["canonical_key"])


class TierModelTests(DbCase):

    def test_every_declared_tier_becomes_a_release(self):
        mm.write_record(self.conn, record())
        got = self.rows("SELECT kind, quality FROM releases ORDER BY id")
        self.assertEqual(got, [("stream", "1080p"), ("stream", "720p"),
                               ("download", "1080p"), ("download", "480p")])

    def test_a_tier_without_a_url_gets_no_source_row(self):
        mm.write_record(self.conn, record())
        urls = [r[0] for r in self.rows(
            "SELECT s.source_url FROM sources s JOIN releases r ON r.id=s.release_id "
            "WHERE r.quality='480p' AND r.kind='download'")]
        self.assertEqual(urls, [], "a tier with no URL must not get an invented one")

    def test_a_dead_mirror_is_kept_with_its_status(self):
        mm.write_record(self.conn, record())
        got = self.rows(
            "SELECT s.status, s.quality FROM sources s JOIN releases r ON r.id=s.release_id "
            "WHERE r.kind='download'")
        self.assertEqual(got, [("dead", "1080p")])

    def test_hls_is_typed_and_http_is_typed_redirect(self):
        mm.write_record(self.conn, record())
        got = dict(self.rows("SELECT s.quality || ':' || r.kind, s.playback_type "
                             "FROM sources s JOIN releases r ON r.id=s.release_id"))
        self.assertEqual(got["1080p:stream"], "hls")
        self.assertEqual(got["1080p:download"], "redirect")

    def test_an_unknown_status_is_refused_whole(self):
        with self.assertRaises(mm.RecordRefused):
            mm.normalize_record(record(streams=[{"quality": "1080p",
                                                 "url": "https://x.invalid/a",
                                                 "status": "maybe"}]))

    def test_a_tier_without_a_recognizable_quality_is_refused(self):
        with self.assertRaises(mm.RecordRefused):
            mm.normalize_record(record(streams=[{"label": "best", "url": "https://x.invalid/a"}]))

    def test_the_same_url_twice_is_stored_once(self):
        mm.write_record(self.conn, record(streams=[
            {"quality": "1080p", "url": "https://cdn.invalid/a.m3u8"},
            {"quality": "1080p", "url": "https://cdn.invalid/a.m3u8"}]))
        self.assertEqual(self.rows(
            "SELECT COUNT(*) FROM sources s JOIN releases r ON r.id=s.release_id "
            "WHERE r.kind='stream'")[0][0], 1)

    def test_a_4k_tier_is_accepted(self):
        rec = mm.normalize_record(record(streams=[{"quality": "4K", "url": "https://x.invalid/k"}]))
        self.assertEqual(rec["streams"][0]["quality"], "4k")


class SubtitleTests(DbCase):

    def test_subtitle_language_tags_survive_verbatim(self):
        subs = ["English subtitles", "CJK subbed", "no-sub"]
        mm.write_record(self.conn, record(subtitles=subs, tags=["Drama"] + subs))
        stored = self.rows("SELECT subtitles, raw_meta FROM posts")[0]
        self.assertEqual(stored[0], ", ".join(subs))
        self.assertEqual(json.loads(stored[1])["subtitles"], subs)
        self.assertEqual(json.loads(stored[1])["tags"], ["Drama"] + subs)

    def test_no_subtitles_is_null_not_empty_string(self):
        mm.write_record(self.conn, record(subtitles=[], tags=[]))
        self.assertIsNone(self.rows("SELECT subtitles FROM posts")[0][0])


class GateTests(unittest.TestCase):

    def test_the_gate_refuses_at_the_ceiling(self):
        self.assertTrue(mm.crawl_blocked(4.0, 8000, 0, 10))

    def test_the_gate_refuses_at_the_memory_floor(self):
        self.assertTrue(mm.crawl_blocked(0.5, 4000, 0, 10))

    def test_the_gate_refuses_another_crawler(self):
        self.assertTrue(mm.crawl_blocked(0.5, 8000, 1, 10))

    def test_the_gate_refuses_an_unbounded_run(self):
        for limit in (None, 0, -5):
            self.assertTrue(mm.crawl_blocked(0.5, 8000, 0, limit), repr(limit))

    def test_the_gate_opens_when_every_condition_holds(self):
        self.assertEqual(mm.crawl_blocked(1.0, 6000, 0, 10), [])


class SyncRefusalTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "missav.db"

    def test_sync_is_refused_and_writes_nothing(self):
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = mm._cmd_sync(type("A", (), {"limit": 25})())
        self.assertIn(rc, (3, 4))
        self.assertFalse(self.db.exists(), "a refused sync must not create a database")
        out = buf.getvalue()
        self.assertTrue("gate conditions not met" in out or "crawl refused at the site" in out)

    def test_sync_never_returns_success(self):
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            rc = mm._cmd_sync(type("A", (), {"limit": 25})())
        self.assertNotEqual(rc, 0, "there is no page to crawl, so no run can succeed")

    def test_the_write_record_cli_refuses_bad_input_before_touching_the_db(self):
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            rc = mm.main(["write-record", "--db", str(self.db), "--json", "/nonexistent.json"])
        self.assertEqual(rc, 2)
        self.assertFalse(self.db.exists())

    def test_the_write_record_cli_refuses_an_invalid_record_without_a_db(self):
        import contextlib
        import io
        bad = Path(self.tmp.name) / "bad.json"
        bad.write_text(json.dumps({"title": "no code at all"}), encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            rc = mm.main(["write-record", "--db", str(self.db), "--json", str(bad)])
        self.assertEqual(rc, 2)
        self.assertIn("not a content code", buf.getvalue())
        self.assertFalse(self.db.exists())


class CaptureBoundaryTests(unittest.TestCase):
    """The absent half must refuse loudly, not return an empty record."""

    def test_extract_record_refuses(self):
        with self.assertRaises(mm.CaptureRequired) as ctx:
            mm.extract_record("<html></html>")
        self.assertIn("Cloudflare", str(ctx.exception))

    def test_parse_item_refuses_too(self):
        with self.assertRaises(mm.CaptureRequired):
            mm.parse_item("<html></html>")

    def test_the_site_reason_names_the_measured_cause(self):
        self.assertIn("Cloudflare", mm.SITE_REASON)
        self.assertIn("robots", mm.SITE_REASON.lower())


class NoInventedUrlTests(DbCase):

    def test_a_record_without_a_url_stores_null(self):
        mm.write_record(self.conn, record(url=None))
        self.assertIsNone(self.rows("SELECT url FROM posts")[0][0],
                          "a URL composed from the code would point at a page nobody saw")

    def test_a_record_url_is_stored_verbatim(self):
        mm.write_record(self.conn, record(url="https://missav.live/en/stars-123"))
        self.assertEqual(self.rows("SELECT url FROM posts")[0][0],
                         "https://missav.live/en/stars-123")

    def test_release_and_source_urls_are_not_synthesized(self):
        mm.write_record(self.conn, record())
        for (origin,) in self.rows("SELECT origin_url FROM releases"):
            self.assertIsNone(origin)
        for (url,) in self.rows("SELECT source_url FROM sources"):
            self.assertTrue(url.startswith("https://cdn.invalid/"))


class SchemaDriftTests(DbCase):

    def test_post_columns_match_the_tuple(self):
        cols = [r[1] for r in self.rows("PRAGMA table_info(posts)")]
        guarded = {"is_18_plus", "is_animated", "scraped_at"}
        # the writer supplies exactly POST_COLUMNS; these three are the schema's
        # own (a NOT NULL DEFAULT 1 guard, a default 0, a timestamp), so the
        # difference must be only them, in both directions — a new column on
        # either side fails this test instead of slipping through
        self.assertEqual(sorted(set(cols) - guarded), sorted(mm.POST_COLUMNS))
        self.assertEqual(set(cols) - set(mm.POST_COLUMNS), guarded)

    def test_release_and_source_columns_match_the_tuples(self):
        rel = [r[1] for r in self.rows("PRAGMA table_info(releases)")][1:]
        src = [r[1] for r in self.rows("PRAGMA table_info(sources)")][1:]
        self.assertEqual(rel, list(mm.RELEASE_COLUMNS))
        self.assertEqual(src, list(mm.SOURCE_COLUMNS))

    def test_the_adult_guard_is_in_the_ddl_not_only_in_python(self):
        ddl = self.rows("SELECT sql FROM sqlite_master WHERE name='posts'")[0][0]
        self.assertIn("CHECK (is_18_plus = 1)", ddl)
        self.assertIn("DEFAULT 1", ddl)


class HygieneTests(unittest.TestCase):

    def test_the_importer_never_names_the_production_catalog(self):
        src = Path(mm.__file__).read_text(encoding="utf-8")
        self.assertTrue(str(mm.DEFAULT_DB_PATH).endswith("missav.db"))
        tree = ast.parse(src)
        literals = [n.value for n in ast.walk(tree)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        for text in literals:
            self.assertNotIn("merged_catalog", text)
            self.assertNotIn("fast_fetch.db", text)

    def test_no_version_word_sits_in_an_adult_literal(self):
        """The fleet law: a version word in an *ADULT* list hides mainstream works.

        This module has no ADULT list today; the test exists so that adding one
        cannot reintroduce the defect `test_database.py` caught in fzmovies."""
        banned = {"uncut", "unrated", "extended", "remastered", "remaster",
                  "restored", "imax", "theatrical", "fanedit", "fansub", "cut"}
        tree = ast.parse(Path(mm.__file__).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if not any(isinstance(t, ast.Name) and "adult" in t.id.lower() for t in targets):
                continue
            if not isinstance(node.value, (ast.List, ast.Tuple, ast.Set)):
                continue
            for el in node.value.elts:
                if isinstance(el, ast.Constant) and isinstance(el.value, str):
                    self.assertFalse(banned & set(re.findall(r"[a-z]+", el.value.lower())),
                                     el.value)

    def test_the_importer_does_not_follow_links(self):
        src = Path(mm.__file__).read_text(encoding="utf-8")
        for opener in ("urlopen", "requests.", "http.client.HTTPSConnection"):
            self.assertNotIn(opener, src, f"{opener} would mean this module can fetch")


if __name__ == "__main__":
    unittest.main(verbosity=2)
