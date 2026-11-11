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
        "severity TEXT, target TEXT, target_detail TEXT, starts_at INTEGER, ends_at INTEGER, "
        "status TEXT)")
    conn.execute(
        "CREATE TABLE tuning_settings (id INTEGER PRIMARY KEY, "
        "theme_mode TEXT, theme_accent TEXT, theme_dynamic_color INTEGER, "
        "theme_hero_autoplay INTEGER, theme_hero_interval_s INTEGER, "
        "hero_max INTEGER, tabs TEXT, disclaimer_text TEXT, "
        "disclaimer_version INTEGER, disclaimer_email TEXT, home_sections_max INTEGER, "
        "section_cap INTEGER, free_quality_cap TEXT, "
        "resolver_concurrency INTEGER, candidate_cap INTEGER, cache_ttl_h INTEGER, "
        "warmup_count INTEGER, warmup_interval_h INTEGER, "
        "rate_limit_play_per_min INTEGER, import_cap INTEGER, "
        "import_concurrency INTEGER, prefetch_queue INTEGER, "
        "prefetch_concurrency INTEGER, domain_check_interval_min INTEGER)")
    conn.execute(
        "CREATE TABLE pauses (id INTEGER PRIMARY KEY, target_type TEXT NOT NULL, "
        "target_id TEXT NOT NULL, is_paused INTEGER NOT NULL DEFAULT 1, "
        "reason TEXT, paused_by INTEGER, paused_at INTEGER, "
        "resumed_at INTEGER, resumed_by INTEGER)")
    conn.execute(
        "CREATE TABLE app_remote_config_history (id INTEGER PRIMARY KEY, "
        "config_version INTEGER NOT NULL, snapshot_json TEXT NOT NULL, "
        "published_by INTEGER, published_at INTEGER)")
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
        "INSERT INTO broadcasts VALUES (?,?,?,?,?,?,?,?,?)", [
            (1, "Hello", "Welcome", "info", "all", None, now - 10, now + 3600, "published"),
            (2, "Draft", "Not yet", "info", "all", None, now - 10, now + 3600, "draft"),
            (3, "Old", "Over", "info", "all", None, now - 7200, now - 3600, "published"),
            (4, "VIP only", "Secret", "info", "vip", None, now - 10, now + 3600, "published"),
            (5, "Future", "Soon", "info", "all", None, now + 3600, now + 7200, "published"),
            (6, "Desi news", "For Desi", "info", "region", "pakistan", now - 10, now + 3600, "published"),
            (7, "New build", "For 1.0.4", "info", "version", "1.0.4", now - 10, now + 3600, "published"),
            (8, "No region", "Nowhere", "info", "region", None, now - 10, now + 3600, "published"),
            (9, "No such target", "Nobody", "info", "everyone", None, now - 10, now + 3600, "published"),
        ])
    conn.execute(
        "INSERT INTO tuning_settings VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (1, "light", "#2BC79A", 1, 0, 8, 4, "my_list,home,home,search",
         "Links come from public sites. We host nothing.", 3, "radddao1@gmail.com", 12, 20, "720p",
         2, 10, 6, 50, 24, 30, 25, 1, 100, 1, 60))
    conn.execute(
        "INSERT INTO app_remote_config_history VALUES (?,?,?,?,?)",
        (1, 5, '{"config": {"min_version_code": 42, "config_version": 5}}',
         1, now))
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

    def test_broadcasts_serve_all_targets_with_detail(self):
        # Every target rides along now — the app filters by its own region,
        # tier and version. Newest first; the draft, the expired and the
        # future one stay out.
        feed = self.feed()
        self.assertEqual(
            [(b["id"], b["target"], b["target_detail"]) for b in feed["broadcasts"]],
            [(7, "version", "1.0.4"), (6, "region", "pakistan"),
             (4, "vip", ""), (1, "all", "")])

    def test_broadcasts_drop_undetailed_and_unknown_targets(self):
        # Row 8 names a region but no region; row 9 names a target the app
        # has no rule for. Neither may leak to the wrong audience.
        feed = self.feed()
        self.assertNotIn(8, [b["id"] for b in feed["broadcasts"]])
        self.assertNotIn(9, [b["id"] for b in feed["broadcasts"]])

    def test_disclaimer_reads_operator_values(self):
        self.assertEqual(
            panel_feed.read_disclaimer(panel_path=self.panel_path),
            {"text": "Links come from public sites. We host nothing.", "version": 3,
             "email": "radddao1@gmail.com"})

    def test_disclaimer_defaults_when_nothing_set(self):
        empty_path = os.path.join(self.tmp.name, "empty.db")
        sqlite3.connect(empty_path).close()
        self.assertEqual(
            panel_feed.read_disclaimer(panel_path=empty_path),
            {"text": "", "version": 0, "email": ""})
        self.assertEqual(
            panel_feed.read_disclaimer(panel_path=os.path.join(self.tmp.name, "nope.db")),
            {"text": "", "version": 0, "email": ""})

    def test_disclaimer_invalid_version_falls_back(self):
        conn = sqlite3.connect(self.panel_path)
        conn.execute(
            "UPDATE tuning_settings SET disclaimer_version=-1, disclaimer_text='' WHERE id=1")
        conn.commit()
        conn.close()
        self.assertEqual(
            panel_feed.read_disclaimer(panel_path=self.panel_path),
            {"text": "", "version": 0, "email": "radddao1@gmail.com"})

    def test_disclaimer_email_not_published_when_invalid(self):
        conn = sqlite3.connect(self.panel_path)
        conn.execute(
            "UPDATE tuning_settings SET disclaimer_email='not-an-email' WHERE id=1")
        conn.commit()
        conn.close()
        self.assertEqual(
            panel_feed.read_disclaimer(panel_path=self.panel_path),
            {"text": "Links come from public sites. We host nothing.", "version": 3,
             "email": ""})

    def test_disclaimer_predates_email_column(self):
        # A panel database from before the email column still answers its
        # text and version; only the email comes back empty.
        old_path = os.path.join(self.tmp.name, "old-panel.db")
        conn = sqlite3.connect(old_path)
        conn.execute(
            "CREATE TABLE tuning_settings (id INTEGER PRIMARY KEY, "
            "disclaimer_text TEXT, disclaimer_version INTEGER)")
        conn.execute(
            "INSERT INTO tuning_settings VALUES (1, 'Old words.', 2)")
        conn.commit()
        conn.close()
        self.assertEqual(
            panel_feed.read_disclaimer(panel_path=old_path),
            {"text": "Old words.", "version": 2, "email": ""})

    def test_section_caps_read_operator_values(self):
        self.assertEqual(
            panel_feed.read_section_caps(panel_path=self.panel_path),
            {"sections_max": 12, "section_cap": 20})

    def test_section_caps_clamp_and_apply(self):
        conn = sqlite3.connect(self.panel_path)
        conn.execute(
            "UPDATE tuning_settings SET home_sections_max=99, section_cap=1 WHERE id=1")
        conn.commit()
        conn.close()
        # 99 clamps to the panel's bound of 12; 1 clamps up to 5.
        self.assertEqual(
            panel_feed.read_section_caps(panel_path=self.panel_path),
            {"sections_max": 12, "section_cap": 5})
        conn = sqlite3.connect(self.panel_path)
        conn.execute(
            "UPDATE tuning_settings SET home_sections_max=1, section_cap=5 WHERE id=1")
        conn.commit()
        conn.close()
        feed = self.feed()
        self.assertEqual(len(feed["sections"]), 1)
        self.assertLessEqual(len(feed["sections"][0]["rows"]), 5)

    def test_free_quality_cap_reads_operator_value(self):
        self.assertEqual(
            panel_feed.read_free_quality_cap(panel_path=self.panel_path), "720p")
        conn = sqlite3.connect(self.panel_path)
        conn.execute(
            "UPDATE tuning_settings SET free_quality_cap='480p' WHERE id=1")
        conn.commit()
        self.assertEqual(
            panel_feed.read_free_quality_cap(panel_path=self.panel_path), "480p")
        conn.execute(
            "UPDATE tuning_settings SET free_quality_cap='4K' WHERE id=1")
        conn.commit()
        conn.close()
        # A value the panel itself would refuse is never the app's cap.
        self.assertEqual(
            panel_feed.read_free_quality_cap(panel_path=self.panel_path), "720p")

    def test_min_version_reads_published_snapshot(self):
        self.assertEqual(
            panel_feed.read_min_version(panel_path=self.panel_path), 42)
        conn = sqlite3.connect(self.panel_path)
        conn.execute("DELETE FROM app_remote_config_history")
        conn.commit()
        conn.close()
        self.assertEqual(
            panel_feed.read_min_version(panel_path=self.panel_path), 0)
        empty_path = os.path.join(self.tmp.name, "empty.db")
        sqlite3.connect(empty_path).close()
        self.assertEqual(panel_feed.read_min_version(panel_path=empty_path), 0)

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
            "INSERT INTO broadcasts VALUES (10, '<b>Hi</b>', 'a & b', 'info', "
            "'all', NULL, ?, ?, 'published')", (self.now - 1, self.now + 100))
        conn.commit()
        conn.close()
        found = [b for b in panel_feed.active_broadcasts(
            panel_path=self.panel_path, now=self.now) if b["id"] == 10]
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

    def test_live_tv_is_a_known_tab_and_readable(self):
        # The app ships a Live TV screen; the backend tab list must accept
        # the id the panel now publishes, and the default list carries it.
        self.assertIn("live_tv", panel_feed.TAB_IDS)
        self.assertIn("live_tv", panel_feed.TABS_DEFAULT)
        conn = sqlite3.connect(self.panel_path)
        conn.execute(
            "UPDATE tuning_settings SET tabs='home,live_tv,search' WHERE id=1")
        conn.commit()
        conn.close()
        self.assertEqual(
            panel_feed.read_tabs(panel_path=self.panel_path),
            ["home", "live_tv", "search"])

    def test_force_update_defaults_when_nothing_published(self):
        # The fixture snapshot has a config but no force-update fields.
        self.assertEqual(
            panel_feed.read_force_update(panel_path=self.panel_path),
            panel_feed.FORCE_UPDATE_DEFAULTS | {"region_order": []})

    def test_force_update_reads_published_snapshot(self):
        import json
        conn = sqlite3.connect(self.panel_path)
        snap = {"config": {
            "min_version_code": 42, "latest_version_code": 350,
            "latest_version_name": "1.0.5", "force_update": 1,
            "force_update_message": "Please update to keep watching.",
            "maintenance_message": "Back soon.",
            "brand_primary": "#2563EB", "brand_accent": "#7C3AED",
            "region_order": "pakistan,india,asia,international"}}
        conn.execute(
            "UPDATE app_remote_config_history SET snapshot_json=? WHERE id=1",
            (json.dumps(snap),))
        conn.commit()
        conn.close()
        self.assertEqual(
            panel_feed.read_force_update(panel_path=self.panel_path),
            {"latest_version_code": 350, "latest_version_name": "1.0.5",
             "force_update": True,
             "force_update_message": "Please update to keep watching.",
             "maintenance_message": "Back soon.",
             "brand_primary": "#2563EB", "brand_accent": "#7C3AED",
             "region_order": ["pakistan", "india", "asia", "international"]})

    def test_force_update_invalid_values_fall_back(self):
        import json
        conn = sqlite3.connect(self.panel_path)
        snap = {"config": {
            "latest_version_code": -5, "latest_version_name": "  ",
            "force_update": 2, "brand_primary": "red",
            "region_order": "pakistan,nowhere,india,pakistan"}}
        conn.execute(
            "UPDATE app_remote_config_history SET snapshot_json=? WHERE id=1",
            (json.dumps(snap),))
        conn.commit()
        conn.close()
        got = panel_feed.read_force_update(panel_path=self.panel_path)
        self.assertEqual(got["latest_version_code"], 0)
        self.assertEqual(got["latest_version_name"], "")
        self.assertFalse(got["force_update"])
        self.assertEqual(got["brand_primary"], "")
        # Unknown regions drop; the duplicate collapses; the order stands.
        self.assertEqual(got["region_order"], ["pakistan", "india"])

    def test_feed_reads_published_snapshot_not_live_table(self):
        # Publish a snapshot whose sections differ from the live table:
        # only one section, "picks", with a single card (post 1). The
        # feed must serve the snapshot, not the live home_sections rows.
        import json
        conn = sqlite3.connect(self.panel_path)
        snap = {"config": {"min_version_code": 42},
                "home": {"sections": [
                    {"section": {"id": 2, "key": "picks", "title": "Picks",
                                 "position": 1, "is_enabled": 1,
                                 "is_adult_only": 0, "visible_to": "all",
                                 "source_rule": "curated",
                                 "category_key": None},
                     "cards": [{"work_id": 1, "is_enabled": 1}]}]}}
        conn.execute(
            "UPDATE app_remote_config_history SET snapshot_json=? WHERE id=1",
            (json.dumps(snap),))
        conn.commit()
        conn.close()
        feed = self.feed()
        self.assertEqual([s["key"] for s in feed["sections"]], ["picks"])
        picks = feed["sections"][0]
        self.assertEqual([int(r["id"]) for r in picks["rows"]], [1])

    def test_feed_falls_back_to_live_table_without_snapshot_home(self):
        # The fixture snapshot has a config but no home block: the feed
        # serves the live home_sections table, as before.
        feed = self.feed()
        self.assertEqual(
            [s["key"] for s in feed["sections"]],
            ["latest", "picks", "comedy"])

    def test_feed_snapshot_ignores_disabled_sections(self):
        import json
        conn = sqlite3.connect(self.panel_path)
        snap = {"config": {},
                "home": {"sections": [
                    {"section": {"id": 1, "key": "off", "title": "Off",
                                 "position": 1, "is_enabled": 0,
                                 "is_adult_only": 0, "visible_to": "all",
                                 "source_rule": "latest",
                                 "category_key": None},
                     "cards": []},
                    {"section": {"id": 2, "key": "latest", "title": "Latest",
                                 "position": 2, "is_enabled": 1,
                                 "is_adult_only": 0, "visible_to": "all",
                                 "source_rule": "latest",
                                 "category_key": None},
                     "cards": []}]}}
        conn.execute(
            "UPDATE app_remote_config_history SET snapshot_json=? WHERE id=1",
            (json.dumps(snap),))
        conn.commit()
        conn.close()
        feed = self.feed()
        self.assertEqual([s["key"] for s in feed["sections"]], ["latest"])

    def test_tuning_knobs_read_operator_values(self):
        self.assertEqual(
            panel_feed.read_tuning_knobs(panel_path=self.panel_path),
            {"resolver_concurrency": 2, "candidate_cap": 10, "cache_ttl_h": 6,
             "warmup_count": 50, "warmup_interval_h": 24,
             "rate_limit_play_per_min": 30, "import_cap": 25,
             "import_concurrency": 1, "prefetch_queue": 100,
             "prefetch_concurrency": 1, "domain_check_interval_min": 60})

    def test_tuning_knobs_clamp_to_panel_bounds(self):
        conn = sqlite3.connect(self.panel_path)
        conn.execute(
            "UPDATE tuning_settings SET resolver_concurrency=99, "
            "candidate_cap=1, cache_ttl_h=0, rate_limit_play_per_min=500, "
            "import_concurrency=0, prefetch_concurrency=9, "
            "domain_check_interval_min=5 WHERE id=1")
        conn.commit()
        conn.close()
        knobs = panel_feed.read_tuning_knobs(panel_path=self.panel_path)
        # The panel's own bounds (1..4, 3..20, 1..24, 10..120, 1..3, 1..2,
        # 30..1440) clamp every out-of-range value to its nearest bound.
        self.assertEqual(knobs["resolver_concurrency"], 4)
        self.assertEqual(knobs["candidate_cap"], 3)
        self.assertEqual(knobs["cache_ttl_h"], 1)
        self.assertEqual(knobs["rate_limit_play_per_min"], 120)
        self.assertEqual(knobs["import_concurrency"], 1)
        self.assertEqual(knobs["prefetch_concurrency"], 2)
        self.assertEqual(knobs["domain_check_interval_min"], 30)

    def test_tuning_knobs_default_when_panel_predates_columns(self):
        # A panel database from before the knob columns still answers the
        # panel's seed defaults — the feed never breaks for an old panel.
        old_path = os.path.join(self.tmp.name, "old-panel.db")
        conn = sqlite3.connect(old_path)
        conn.execute(
            "CREATE TABLE tuning_settings (id INTEGER PRIMARY KEY, "
            "theme_mode TEXT)")
        conn.execute("INSERT INTO tuning_settings VALUES (1, 'dark')")
        conn.commit()
        conn.close()
        knobs = panel_feed.read_tuning_knobs(panel_path=old_path)
        self.assertEqual(knobs, {
            name: default
            for name, (default, _lo, _hi) in panel_feed.TUNING_KNOBS.items()})

    def test_tuning_knob_falls_back_to_caller_default_when_unwired(self):
        # The single-knob primitive answers the CALLER's default when the
        # panel cannot answer — a consumer's shipped behaviour is its own,
        # not the panel's seed.
        self.assertEqual(
            panel_feed.tuning_knob(
                panel_path=os.path.join(self.tmp.name, "nope.db"),
                name="candidate_cap", default=5),
            5)
        self.assertEqual(
            panel_feed.tuning_knob(
                panel_path=self.panel_path,
                name="candidate_cap", default=5),
            10)
        self.assertEqual(
            panel_feed.tuning_knob(
                panel_path=self.panel_path,
                name="no_such_knob", default=7),
            7)

    def test_is_paused_reads_live_pause_rows(self):
        self.assertFalse(panel_feed.is_paused(
            panel_path=self.panel_path,
            target_type="broadcast", target_id="1"))
        conn = sqlite3.connect(self.panel_path)
        conn.execute(
            "INSERT INTO pauses (target_type, target_id, is_paused, "
            "resumed_at) VALUES ('broadcast', '1', 1, NULL)")
        conn.execute(
            "INSERT INTO pauses (target_type, target_id, is_paused, "
            "resumed_at) VALUES ('section', 'latest', 1, 123)")
        conn.commit()
        conn.close()
        # The broadcast pause is live; the section pause was resumed.
        self.assertTrue(panel_feed.is_paused(
            panel_path=self.panel_path,
            target_type="broadcast", target_id="1"))
        self.assertFalse(panel_feed.is_paused(
            panel_path=self.panel_path,
            target_type="section", target_id="latest"))

    def test_paused_broadcast_is_not_served(self):
        conn = sqlite3.connect(self.panel_path)
        conn.execute(
            "INSERT INTO pauses (target_type, target_id, is_paused, "
            "resumed_at) VALUES ('broadcast', '1', 1, NULL)")
        conn.commit()
        conn.close()
        ids = [b["id"] for b in panel_feed.active_broadcasts(
            panel_path=self.panel_path, now=self.now)]
        self.assertNotIn(1, ids)
        # The other published broadcasts still serve.
        self.assertIn(4, ids)

    def test_paused_section_is_not_served(self):
        conn = sqlite3.connect(self.panel_path)
        conn.execute(
            "INSERT INTO pauses (target_type, target_id, is_paused, "
            "resumed_at) VALUES ('section', 'latest', 1, NULL)")
        conn.commit()
        conn.close()
        feed = self.feed()
        self.assertNotIn("latest", [s["key"] for s in feed["sections"]])
        self.assertIn("picks", [s["key"] for s in feed["sections"]])

    def test_paused_category_section_is_not_served(self):
        conn = sqlite3.connect(self.panel_path)
        conn.execute(
            "INSERT INTO pauses (target_type, target_id, is_paused, "
            "resumed_at) VALUES ('category', 'comedy', 1, NULL)")
        conn.commit()
        conn.close()
        feed = self.feed()
        self.assertNotIn("comedy", [s["key"] for s in feed["sections"]])

    def test_paused_features_lists_only_live_feature_pauses(self):
        self.assertEqual(
            panel_feed.paused_features(panel_path=self.panel_path), set())
        conn = sqlite3.connect(self.panel_path)
        conn.execute(
            "INSERT INTO pauses (target_type, target_id, is_paused, "
            "resumed_at) VALUES ('feature', 'downloads', 1, NULL)")
        conn.execute(
            "INSERT INTO pauses (target_type, target_id, is_paused, "
            "resumed_at) VALUES ('feature', 'chromecast', 1, 123)")
        conn.execute(
            "INSERT INTO pauses (target_type, target_id, is_paused, "
            "resumed_at) VALUES ('broadcast', '1', 1, NULL)")
        conn.commit()
        conn.close()
        # Only the live feature pause (downloads) is listed; the resumed
        # chromecast pause and the broadcast pause are not features.
        self.assertEqual(
            panel_feed.paused_features(panel_path=self.panel_path),
            {"downloads"})

    def test_hero_falls_back_to_latest_when_curated_is_empty(self):
        # A curated hero with no live cards must not leave the top of
        # Home empty: it fills with the newest posts.
        import json
        conn = sqlite3.connect(self.panel_path)
        snap = {"config": {},
                "home": {"sections": [
                    {"section": {"id": 1, "key": "hero", "title": "Hero",
                                 "position": 1, "is_enabled": 1,
                                 "is_adult_only": 0, "visible_to": "all",
                                 "source_rule": "curated",
                                 "category_key": None},
                     "cards": []}]}}
        conn.execute(
            "UPDATE app_remote_config_history SET snapshot_json=? WHERE id=1",
            (json.dumps(snap),))
        conn.commit()
        conn.close()
        feed = self.feed()
        hero = [s for s in feed["sections"] if s["key"] == "hero"][0]
        # Newest first, adult row out, hidden row (2) out.
        self.assertEqual(
            [int(r["id"]) for r in hero["rows"]], [6, 5, 3, 1])


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
