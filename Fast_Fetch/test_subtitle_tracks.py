"""Offline tests for server-side subtitle tracks (Gap A3).

The module normalises subtitle entries to the wire shape the app parses,
stores them keyed by ledger link id, and reads them back for the bundle.
Every test runs on an in-memory database; nothing here touches the live
catalog, and the write path is asserted never to commit the caller's
transaction.
"""

import os
import sqlite3
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import subtitle_tracks


class NormalizeTests(unittest.TestCase):
    def test_resolver_shape_maps_language_and_format(self):
        track = subtitle_tracks.normalize_track(
            {"language": "English",
             "url": "https://cdn.example.com/film.en.srt"})
        self.assertEqual(track, {
            "lang": "en", "kind": "subtitles",
            "subtitle_url": "https://cdn.example.com/film.en.srt",
            "format": "srt", "default": False, "forced": False,
        })

    def test_hindi_and_urdu_names_map_to_codes(self):
        self.assertEqual(
            subtitle_tracks.normalize_track(
                {"language": "Hindi", "url": "https://cdn.example.com/hi.vtt"})["lang"], "hi")
        self.assertEqual(
            subtitle_tracks.normalize_track(
                {"language": "Urdu", "url": "https://cdn.example.com/ur.vtt"})["lang"], "ur")

    def test_bare_url_string_is_a_track_with_unknown_language(self):
        track = subtitle_tracks.normalize_track("https://cdn.example.com/subs.ass")
        self.assertEqual(track["lang"], "")
        self.assertEqual(track["format"], "ass")
        self.assertEqual(track["subtitle_url"], "https://cdn.example.com/subs.ass")

    def test_non_https_urls_are_dropped_never_served(self):
        for bad in ("http://cdn.example.com/subs.srt",
                    "/relative/subs.srt", "", None, 42):
            self.assertIsNone(subtitle_tracks.normalize_track({"url": bad}),
                              bad)

    def test_unknown_format_is_kept_without_a_format_hint(self):
        track = subtitle_tracks.normalize_track(
            {"language": "en", "url": "https://cdn.example.com/subs.xyz"})
        self.assertIsNone(track["format"])
        self.assertEqual(track["subtitle_url"], "https://cdn.example.com/subs.xyz")

    def test_wire_shape_round_trips(self):
        track = subtitle_tracks.normalize_track(
            {"lang": "en", "kind": "subtitles",
             "url": "https://cdn.example.com/en.vtt", "format": "vtt",
             "default": True, "forced": True})
        self.assertEqual(track["default"], True)
        self.assertEqual(track["forced"], True)

    def test_dedupes_by_lang_and_url_in_first_seen_order(self):
        tracks = subtitle_tracks.normalize_tracks([
            {"language": "en", "url": "https://cdn.example.com/a.srt"},
            {"language": "en", "url": "https://cdn.example.com/a.srt"},
            {"language": "hi", "url": "https://cdn.example.com/a.srt"},
            {"url": "http://cdn.example.com/bad.srt"},
        ])
        self.assertEqual(
            [(t["lang"], t["subtitle_url"]) for t in tracks],
            [("en", "https://cdn.example.com/a.srt"),
             ("hi", "https://cdn.example.com/a.srt")])


class ExtractFromRawMetaTests(unittest.TestCase):
    def test_list_dicts_strings_and_single_values(self):
        self.assertEqual(
            subtitle_tracks.extract_from_raw_meta(
                {"subtitles": [{"language": "en", "url": "https://x/y.srt"}]}),
            [{"language": "en", "url": "https://x/y.srt"}])
        self.assertEqual(
            subtitle_tracks.extract_from_raw_meta(
                {"subtitles": "https://x/y.srt"}),
            ["https://x/y.srt"])
        self.assertEqual(
            subtitle_tracks.extract_from_raw_meta(
                {"subtitles": {"language": "en", "url": "https://x/y.srt"}}),
            [{"language": "en", "url": "https://x/y.srt"}])

    def test_no_subtitles_is_not_an_error(self):
        for blob in (None, {}, {"title": "Dune"}, {"subtitles": None},
                     {"subtitles": 42}, "not a dict"):
            self.assertEqual(subtitle_tracks.extract_from_raw_meta(blob), [])


class StoreAndReadTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")

    def tearDown(self):
        self.conn.close()

    def test_upsert_then_read_returns_the_wire_shape(self):
        count = subtitle_tracks.upsert_tracks(
            self.conn, 7,
            [{"language": "en", "url": "https://cdn.example.com/en.srt"},
             {"language": "hi", "url": "https://cdn.example.com/hi.vtt"}],
            source="resolve")
        self.assertEqual(count, 2)
        found = subtitle_tracks.tracks_for_links(self.conn, [7])
        self.assertEqual(found[7], [
            {"lang": "en", "kind": "subtitles",
             "subtitle_url": "https://cdn.example.com/en.srt", "format": "srt",
             "default": False, "forced": False},
            {"lang": "hi", "kind": "subtitles",
             "subtitle_url": "https://cdn.example.com/hi.vtt", "format": "vtt",
             "default": False, "forced": False},
        ])

    def test_upsert_replaces_instead_of_duplicating(self):
        subtitle_tracks.upsert_tracks(
            self.conn, 7,
            [{"language": "en", "url": "https://cdn.example.com/en.srt",
              "default": False}])
        subtitle_tracks.upsert_tracks(
            self.conn, 7,
            [{"language": "en", "url": "https://cdn.example.com/en.srt",
              "default": True}])
        found = subtitle_tracks.tracks_for_links(self.conn, [7])
        self.assertEqual(len(found[7]), 1)
        self.assertTrue(found[7][0]["default"])

    def test_links_without_tracks_are_absent_not_empty(self):
        subtitle_tracks.upsert_tracks(
            self.conn, 7,
            [{"language": "en", "url": "https://cdn.example.com/en.srt"}])
        found = subtitle_tracks.tracks_for_links(self.conn, [7, 8, 9])
        self.assertEqual(sorted(found), [7])

    def test_read_is_safe_without_the_table(self):
        # A database that never stored a track answers {}, and never
        # creates the table as a side effect of a read.
        self.assertEqual(subtitle_tracks.tracks_for_links(self.conn, [7]), {})
        row = self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name = 'subtitle_tracks'"
        ).fetchone()
        self.assertIsNone(row)

    def test_upsert_does_not_commit_the_callers_transaction(self):
        subtitle_tracks.upsert_tracks(
            self.conn, 7,
            [{"language": "en", "url": "https://cdn.example.com/en.srt"}])
        # A commit would have closed the transaction; the caller still owns it.
        self.assertTrue(self.conn.in_transaction)
        self.conn.rollback()
        self.assertEqual(subtitle_tracks.tracks_for_links(self.conn, [7]), {})

    def test_record_resolver_subtitles_never_raises(self):
        self.assertEqual(
            subtitle_tracks.record_resolver_subtitles(
                self.conn, 7,
                {"subtitles": [{"language": "en",
                                "url": "https://cdn.example.com/en.srt"}]}),
            1)
        self.assertEqual(
            subtitle_tracks.tracks_for_links(self.conn, [7])[7][0]["lang"], "en")
        for bad in (None, {}, {"subtitles": []}, {"subtitles": None},
                    "not a dict", {"subtitles": [{"url": "http://x/y.srt"}]}):
            self.assertEqual(
                subtitle_tracks.record_resolver_subtitles(self.conn, 7, bad), 0)


class HarvestFromStagingTests(unittest.TestCase):
    def setUp(self):
        self.staging = sqlite3.connect(":memory:")
        self.staging.execute(
            "CREATE TABLE posts (post_canonical_key TEXT, raw_meta TEXT)")
        self.staging.execute(
            "CREATE TABLE sources (post_canonical_key TEXT, source_url TEXT)")
        self.live = sqlite3.connect(":memory:")
        self.live.execute(
            "CREATE TABLE download_sources (id INTEGER PRIMARY KEY, source_url TEXT)")
        self.live.execute(
            "INSERT INTO download_sources (id, source_url) VALUES (11, 'https://site.example/dune')")
        self.live.execute(
            "INSERT INTO download_sources (id, source_url) VALUES (12, 'https://site.example/other')")
        self.live.commit()

    def tearDown(self):
        self.staging.close()
        self.live.close()

    def _stage_post(self, key, raw_meta, source_url):
        import json

        self.staging.execute(
            "INSERT INTO posts (post_canonical_key, raw_meta) VALUES (?, ?)",
            (key, json.dumps(raw_meta)))
        self.staging.execute(
            "INSERT INTO sources (post_canonical_key, source_url) VALUES (?, ?)",
            (key, source_url))
        self.staging.commit()

    def test_harvest_maps_staging_subtitles_onto_ledger_links(self):
        self._stage_post("dune-2024",
                         {"subtitles": [{"language": "en",
                                         "url": "https://cdn.example.com/en.srt"}]},
                         "https://site.example/dune")
        counts = subtitle_tracks.harvest_from_staging(self.staging, self.live)
        self.assertEqual(counts, {"scanned": 1, "with_subtitles": 1,
                                  "matched": 1, "tracks": 1})
        found = subtitle_tracks.tracks_for_links(self.live, [11])
        self.assertEqual(found[11][0]["subtitle_url"], "https://cdn.example.com/en.srt")

    def test_unmerged_sources_are_skipped_not_invented(self):
        self._stage_post("never-merged",
                         {"subtitles": [{"language": "en",
                                         "url": "https://cdn.example.com/en.srt"}]},
                         "https://site.example/never-merged")
        counts = subtitle_tracks.harvest_from_staging(self.staging, self.live)
        self.assertEqual(counts["matched"], 0)
        self.assertEqual(counts["tracks"], 0)
        self.assertEqual(subtitle_tracks.tracks_for_links(self.live, [11, 12]), {})

    def test_posts_without_subtitles_are_scanned_not_counted(self):
        self._stage_post("plain", {"title": "Dune"}, "https://site.example/dune")
        counts = subtitle_tracks.harvest_from_staging(self.staging, self.live)
        self.assertEqual(counts, {"scanned": 1, "with_subtitles": 0,
                                  "matched": 0, "tracks": 0})


if __name__ == "__main__":
    unittest.main()
