#!/usr/bin/env python3
"""Tests for the admin panel feed (`panel_feed.py`): sections, broadcasts, hides.

Fixtures are built the way the panel builds them: a catalog with post rows and
a panel database with the four tables the feed reads (`home_sections`,
`slider_cards`, `content_visibility`, `broadcasts`). Nothing is hand-waved:
every assertion names the exact rows that must appear, and the exact rows that
must not — above all the adult-flagged row, which must never reach a section
on any rule.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

import panel_feed
import viewer

HERE = Path(__file__).parent

POST_COLUMNS = (
    "id INTEGER PRIMARY KEY, title TEXT, clean_title TEXT, year INTEGER, "
    "content_type TEXT, seasons TEXT, poster_url TEXT, backdrop_urls TEXT, "
    "imdb_rating TEXT, imdb_id TEXT, tmdb_id TEXT, genres TEXT, "
    "synopsis TEXT, is_animated INTEGER, industry TEXT, country TEXT, "
    "language TEXT, is_18_plus INTEGER, source_site TEXT, "
    "canonical_key TEXT, slug TEXT"
)


def _make_post(post_id, title, *, adult=None, genres="Action", ctype="movie",
               year=2024):
    return (post_id, title, title.lower(), year, ctype, None, None, None,
            None, None, None, genres, None, 0, None, None, None, adult,
            None, "key-%d" % post_id, "slug-%d" % post_id)


def _build_catalog(path):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE posts (%s)" % POST_COLUMNS)
    conn.execute("CREATE TABLE releases (id INTEGER PRIMARY KEY, post_id INTEGER, release_title TEXT, quality TEXT, codec TEXT, languages TEXT)")
    conn.execute("CREATE TABLE download_sources (id INTEGER PRIMARY KEY, release_id INTEGER)")
    conn.execute(
        "CREATE TABLE cat_works (id INTEGER PRIMARY KEY, title TEXT, year INTEGER, "
        "work_type TEXT, work_key TEXT, poster_url TEXT, genres TEXT, "
        "imdb_rating TEXT, is_18_plus INTEGER, is_animated INTEGER, "
        "languages TEXT, synopsis TEXT, best_quality_score REAL, "
        "release_count INTEGER)")
    rows = [
        _make_post(1, "One", genres="Action", year=2024),
        _make_post(2, "Two", genres="Comedy", year=2023),
        _make_post(3, "Three", genres="Action", year=2025),
        _make_post(4, "Four Adult", adult=1, genres="Action"),
        _make_post(5, "Five Unknown", adult=None, genres="Drama"),
        _make_post(6, "Six Series", ctype="series", genres="Drama"),
    ]
    conn.executemany("INSERT INTO posts VALUES (%s)" % ",".join("?" * 21), rows)
    conn.commit()
    conn.close()


def _build_panel(path):
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE home_sections (id INTEGER PRIMARY KEY, key TEXT UNIQUE, "
        "title TEXT, position INTEGER, is_enabled INTEGER, is_adult_only INTEGER, "
        "visible_to TEXT, source_rule TEXT, category_key TEXT)")
    conn.execute(
        "CREATE TABLE slider_cards (id INTEGER PRIMARY KEY, section_id INTEGER, "
        "work_id INTEGER, position INTEGER, title_override TEXT, "
        "is_enabled INTEGER, starts_at INTEGER, ends_at INTEGER)")
    conn.execute(
        "CREATE TABLE content_visibility (id INTEGER PRIMARY KEY, scope TEXT, "
        "scope_id TEXT, is_hidden INTEGER, reason TEXT, note TEXT, "
        "expires_at INTEGER, restored_at INTEGER)")
    conn.execute(
        "CREATE TABLE broadcasts (id INTEGER PRIMARY KEY, title TEXT, body TEXT, "
        "severity TEXT, target TEXT, starts_at INTEGER, ends_at INTEGER, "
        "status TEXT)")
    conn.execute(
        "CREATE TABLE tuning_settings (id INTEGER PRIMARY KEY, "
        "theme_mode TEXT, theme_accent TEXT, theme_dynamic_color INTEGER, "
        "theme_hero_autoplay INTEGER, theme_hero_interval_s INTEGER, "
        "hero_max INTEGER, tabs TEXT)")
    now = 1_791_000_000
    conn.executemany(
        "INSERT INTO home_sections VALUES (?,?,?,?,?,?,?,?,?)", [
            (1, "latest", "Latest", 1, 1, 0, "all", "latest", None),
            (2, "picks", "Picks", 2, 1, 0, "all", "curated", None),
            (3, "comedy", "Comedy", 3, 1, 0, "all", "category", "comedy"),
            (4, "grown", "Grown", 4, 1, 1, "all", "latest", None),
            (5, "off", "Off", 5, 0, 0, "all", "latest", None),
        ])
    conn.executemany(
        "INSERT INTO slider_cards VALUES (?,?,?,?,?,?,?,?)", [
            (1, 2, 3, 1, None, 1, None, None),
            (2, 2, 1, 2, None, 1, None, None),
            (3, 2, 99, 3, None, 1, None, None),
            (4, 2, 2, 4, None, 0, None, None),
        ])
    conn.executemany(
        "INSERT INTO content_visibility VALUES (?,?,?,?,?,?,?,?)", [
            (1, "work", "2", 1, "takedown", None, None, None),
            (2, "section_work", "latest:3", 1, "bad art", None, None, None),
            (3, "work", "6", 1, "expired", None, now - 100, None),
            (4, "work", "5", 1, "restored", None, None, now - 10),
        ])
    conn.executemany(
        "INSERT INTO broadcasts VALUES (?,?,?,?,?,?,?,?)", [
            (1, "Hello", "Welcome", "info", "all", now - 10, now + 3600, "published"),
            (2, "Draft", "Not yet", "info", "all", now - 10, now + 3600, "draft"),
            (3, "Old", "Over", "info", "all", now - 7200, now - 3600, "published"),
            (4, "VIP only", "Secret", "info", "vip", now - 10, now + 3600, "published"),
            (5, "Future", "Soon", "info", "all", now + 3600, now + 7200, "published"),
        ])
    conn.execute(
        "INSERT INTO tuning_settings VALUES (?,?,?,?,?,?,?,?)",
        (1, "light", "#2BC79A", 1, 0, 8, 4, "my_list,home,home,search"))
    conn.commit()
    conn.close()
    return now


class PanelFeedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.catalog_path = os.path.join(self.tmp.name, "catalog.db")
        self.panel_path = os.path.join(self.tmp.name, "admin_v2.db")
        _build_catalog(self.catalog_path)
        self.now = _build_panel(self.panel_path)
        self.catalog = sqlite3.connect(self.catalog_path)
        self.catalog.row_factory = sqlite3.Row

    def tearDown(self):
        self.catalog.close()
        self.tmp.cleanup()

    def feed(self):
        return panel_feed.load_panel_feed(
            self.catalog, panel_path=self.panel_path, now=self.now)

    def test_latest_section_is_newest_first_and_capped(self):
        feed = self.feed()
        latest = [s for s in feed["sections"] if s["key"] == "latest"][0]
        ids = [int(r["id"]) for r in latest["rows"]]
        # 6 newest, then 5, then 1; 4 is adult, 3 is hidden in this section,
        # 2 is hidden everywhere.
        self.assertEqual(ids, [6, 5, 1])

    def test_curated_section_keeps_card_order_and_skips_missing(self):
        feed = self.feed()
        picks = [s for s in feed["sections"] if s["key"] == "picks"][0]
        ids = [int(r["id"]) for r in picks["rows"]]
        # Cards order 3, 1, 99 (missing), 2 (disabled card); 2 is also hidden.
        self.assertEqual(ids, [3, 1])

    def test_category_section_filters_by_genre(self):
        feed = self.feed()
        comedy = [s for s in feed["sections"] if s["key"] == "comedy"][0]
        ids = [int(r["id"]) for r in comedy["rows"]]
        # Only post 2 is Comedy, and it is hidden everywhere.
        self.assertEqual(ids, [])

    def test_adult_only_section_is_not_served(self):
        feed = self.feed()
        keys = [s["key"] for s in feed["sections"]]
        self.assertNotIn("grown", keys)

    def test_disabled_section_is_not_served(self):
        feed = self.feed()
        keys = [s["key"] for s in feed["sections"]]
        self.assertNotIn("off", keys)

    def test_adult_flagged_row_never_appears(self):
        feed = self.feed()
        seen = [int(r["id"]) for s in feed["sections"] for r in s["rows"]]
        self.assertNotIn(4, seen)
        # An unknown flag (NULL) is public on the public edge, so it appears.
        self.assertIn(5, seen)

    def test_section_work_hide_only_hides_in_that_section(self):
        feed = self.feed()
        latest = [s for s in feed["sections"] if s["key"] == "latest"][0]
        picks = [s for s in feed["sections"] if s["key"] == "picks"][0]
        self.assertNotIn(3, [int(r["id"]) for r in latest["rows"]])
        self.assertIn(3, [int(r["id"]) for r in picks["rows"]])

    def test_hidden_work_ids_lists_only_live_global_hides(self):
        feed = self.feed()
        # 2 is hidden; 6 expired; 5 restored; section_work is not global.
        self.assertEqual(feed["hidden_work_ids"], [2])

    def test_broadcasts_only_published_live_all_target(self):
        feed = self.feed()
        self.assertEqual(
            [(b["id"], b["title"]) for b in feed["broadcasts"]],
            [(1, "Hello")])

    def test_missing_panel_db_returns_empty_without_raising(self):
        feed = panel_feed.load_panel_feed(
            self.catalog, panel_path=os.path.join(self.tmp.name, "nope.db"),
            now=self.now)
        self.assertEqual(
            feed, {"sections": [], "broadcasts": [], "hidden_work_ids": []})

    def test_missing_tables_returns_empty_without_raising(self):
        empty_path = os.path.join(self.tmp.name, "empty.db")
        sqlite3.connect(empty_path).close()
        feed = panel_feed.load_panel_feed(
            self.catalog, panel_path=empty_path, now=self.now)
        self.assertEqual(
            feed, {"sections": [], "broadcasts": [], "hidden_work_ids": []})

    def test_hidden_work_ids_standalone(self):
        self.assertEqual(
            panel_feed.hidden_work_ids(panel_path=self.panel_path, now=self.now),
            {2})

    def test_broadcast_text_is_scrubbed(self):
        conn = sqlite3.connect(self.panel_path)
        conn.execute(
            "INSERT INTO broadcasts VALUES (9, '<b>Hi</b>', 'a & b', 'info', "
            "'all', ?, ?, 'published')", (self.now - 1, self.now + 100))
        conn.commit()
        conn.close()
        found = [b for b in panel_feed.active_broadcasts(
            panel_path=self.panel_path, now=self.now) if b["id"] == 9]
        self.assertEqual(len(found), 1)
        self.assertNotIn("<", found[0]["title"])
        self.assertNotIn("<", found[0]["body"])

    def test_theme_reads_operator_values(self):
        self.assertEqual(
            panel_feed.read_theme(panel_path=self.panel_path),
            {"mode": "light", "accent": "#2BC79A", "dynamic_color": True,
             "hero_autoplay": False, "hero_interval_s": 8, "hero_max": 4})

    def test_theme_defaults_when_nothing_set(self):
        empty_path = os.path.join(self.tmp.name, "empty.db")
        sqlite3.connect(empty_path).close()
        self.assertEqual(
            panel_feed.read_theme(panel_path=empty_path),
            panel_feed.THEME_DEFAULTS)
        self.assertEqual(
            panel_feed.read_theme(panel_path=os.path.join(self.tmp.name, "nope.db")),
            panel_feed.THEME_DEFAULTS)

    def test_tabs_reads_operator_order_deduped(self):
        # The fixture order is my_list, home, home, search: the duplicate
        # collapses, the order stands, and settings is absent because the
        # operator did not list it — the list is authoritative.
        self.assertEqual(
            panel_feed.read_tabs(panel_path=self.panel_path),
            ["my_list", "home", "search"])

    def test_tabs_defaults_when_nothing_set(self):
        empty_path = os.path.join(self.tmp.name, "empty.db")
        sqlite3.connect(empty_path).close()
        self.assertEqual(
            panel_feed.read_tabs(panel_path=empty_path),
            panel_feed.TABS_DEFAULT)
        self.assertEqual(
            panel_feed.read_tabs(panel_path=os.path.join(self.tmp.name, "nope.db")),
            panel_feed.TABS_DEFAULT)

    def test_tabs_unknown_ids_dropped_and_empty_falls_back(self):
        conn = sqlite3.connect(self.panel_path)
        conn.execute(
            "UPDATE tuning_settings SET tabs='home,nope,search' WHERE id=1")
        conn.commit()
        self.assertEqual(
            panel_feed.read_tabs(panel_path=self.panel_path),
            ["home", "search"])
        conn.execute("UPDATE tuning_settings SET tabs='' WHERE id=1")
        conn.commit()
        conn.close()
        self.assertEqual(
            panel_feed.read_tabs(panel_path=self.panel_path),
            panel_feed.TABS_DEFAULT)

    def test_theme_invalid_values_fall_back_to_defaults(self):
        conn = sqlite3.connect(self.panel_path)
        conn.execute(
            "UPDATE tuning_settings SET theme_mode='pink', "
            "theme_accent='red', theme_hero_interval_s=99, hero_max=99 "
            "WHERE id=1")
        conn.commit()
        conn.close()
        theme = panel_feed.read_theme(panel_path=self.panel_path)
        self.assertEqual(theme["mode"], "dark")
        self.assertEqual(theme["accent"], "")
        self.assertEqual(theme["hero_interval_s"], 5)
        self.assertEqual(theme["hero_max"], 6)
        # The valid values in the same row still survive the bad ones.
        self.assertTrue(theme["dynamic_color"])
        self.assertFalse(theme["hero_autoplay"])


class PostsHideTests(unittest.TestCase):
    """The panel hide is enforced in the posts route itself, so even an old
    app that never reads the feed obeys it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.catalog_path = os.path.join(self.tmp.name, "catalog.db")
        self.panel_path = os.path.join(self.tmp.name, "admin_v2.db")
        _build_catalog(self.catalog_path)
        self.now = _build_panel(self.panel_path)
        self.env_patch = mock.patch.dict(
            os.environ, {"RADD_ADMIN_V2_DB": self.panel_path})
        self.env_patch.start()

    def tearDown(self):
        self.env_patch.stop()
        self.tmp.cleanup()

    def test_hidden_work_is_absent_from_posts_and_total(self):
        with mock.patch.object(viewer, "DB_PATH", self.catalog_path):
            with mock.patch.object(viewer, "_ensure_schema", lambda: None):
                resp = viewer.api_v1_get_posts(limit=10)
        ids = [item["id"] for item in resp["results"]]
        self.assertNotIn(2, ids)
        self.assertEqual(resp["total"], 4)
        # The adult row is hidden by the adult clause, the hidden row by the panel.
        self.assertNotIn(4, ids)

    def test_no_panel_db_means_no_hides(self):
        with mock.patch.dict(os.environ, {"RADD_ADMIN_V2_DB": "/nonexistent/x.db"}):
            with mock.patch.object(viewer, "DB_PATH", self.catalog_path):
                with mock.patch.object(viewer, "_ensure_schema", lambda: None):
                    resp = viewer.api_v1_get_posts(limit=10)
        ids = [item["id"] for item in resp["results"]]
        self.assertIn(2, ids)
        self.assertEqual(resp["total"], 5)


if __name__ == "__main__":
    unittest.main()
