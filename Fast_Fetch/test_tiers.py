"""Offline tests for one best-and-fastest option per quality tier.

The rule these protect is the owner's product decision: a viewer sees one row
per quality, not the six copies the ledger holds for it, and the row says what
the picture is and how it behaves — never who serves it.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fast_fetch
import redact
import tiers
import viewer


def link(**fields) -> dict:
    base = {"id": 1, "release_id": 7, "playback_type": "direct", "status": "active",
            "is_resumable": 0, "is_temporary": 0, "http_status": None,
            "file_size_bytes": None, "mime_type": None,
            "last_checked_at": None, "created_at": None}
    base.update(fields)
    return base


class BandTests(unittest.TestCase):
    def test_a_scraper_quality_string_becomes_a_band(self):
        for text, band in (
                ("4K", "2160p"), ("2160p UHD", "2160p"), ("HDR10+", "2160p"),
                ("1080P", "1080p"), ("720p WEB-DL", "720p"), ("480p-HEVC", "480p"),
                ("360p", "sd"), ("HDCAM", "sd"), ("HD", "720p"),
                ("Download", tiers.UNSPECIFIED), ("unknown", tiers.UNSPECIFIED)):
            self.assertEqual(tiers.band_of(text), band, text)

    def test_only_the_structured_columns_choose_a_band(self):
        # A headline is a scraper's sentence: "Camera" must not read as a cam rip.
        self.assertEqual(tiers.for_release(
            {"quality": "1080p", "release_title": "Camera (2017) Sand"},
            [link()])["tiers"][0]["band"], "1080p")

    def test_a_headline_word_never_overrides_the_print(self):
        self.assertEqual(tiers.band_of("480p", "x264", "1GB"), "480p")


class WinnerTests(unittest.TestCase):
    def test_the_live_resumable_copy_in_the_right_size_window_wins(self):
        slow = link(id=1, is_resumable=0, file_size_bytes=40_000_000,
                    last_checked_at="2025-01-01 00:00:00")
        best = link(id=2, is_resumable=1, file_size_bytes=2_000_000_000,
                    http_status=200, last_checked_at="2026-10-01 00:00:00")
        dead = link(id=3, status="dead", is_resumable=1)
        ladder = tiers.for_release({"quality": "1080p"}, [slow, best, dead])
        self.assertEqual(ladder["tiers"][0]["link"]["id"], 2)
        self.assertEqual(ladder["tiers"][0]["copies"], 3)
        self.assertEqual(len(ladder["tiers"]), 1, "six copies, one row")

    def test_an_embed_never_wins_a_play_tier(self):
        # The owner asked for one player and the embed surfaces gone. A tier whose
        # only copy is an embed is therefore offered honestly as download-only,
        # not as a player that silently cannot start.
        embed = link(id=4, playback_type="iframe")
        ladder = tiers.for_release({"quality": "720p"}, [embed])
        self.assertFalse(ladder["tiers"][0]["playable"])
        self.assertEqual(ladder["tiers"][0]["mode"], "download_only")
        self.assertIsNone(ladder["auto"])

    def test_a_direct_file_beats_a_link_that_must_be_resolved(self):
        page = link(id=5, playback_type="url")
        direct = link(id=6, playback_type="direct")
        self.assertEqual(
            tiers.score(direct, "1080p") > tiers.score(page, "1080p"), True)

    def test_a_dead_copy_loses_to_a_live_one_at_the_same_band(self):
        live = link(id=7, status="active")
        dead = link(id=8, status="dead", is_resumable=1)
        self.assertGreater(tiers.score(live, "1080p"), tiers.score(dead, "1080p"))

    def test_a_tier_label_never_names_a_server(self):
        ladder = tiers.for_release({"quality": "1080p", "codec": "x265"}, [link()])
        label = ladder["tiers"][0]["label"]
        self.assertIn("Full HD", label)
        self.assertNotIn("cdn", label.lower())


class AutoDefaultTests(unittest.TestCase):
    def test_auto_is_the_best_playable_band_not_the_highest_one(self):
        # 4K exists here but only as an embed, so the player defaults to 1080p and
        # 2160p stays honest as a download.
        hd = tiers.for_release({"quality": "1080p"}, [link(id=1)])
        uhd = tiers.for_release({"quality": "2160p"},
                                [link(id=2, playback_type="iframe")])
        merged = tiers.merge([hd, uhd])
        self.assertEqual(merged["auto"]["band"], "1080p")
        self.assertEqual(merged["download_only_bands"], ["2160p"])
        self.assertEqual([t["band"] for t in merged["tiers"]], ["2160p", "1080p"])


class MergeTests(unittest.TestCase):
    def test_prints_of_the_same_band_collapse_to_their_best_copy(self):
        one = tiers.for_release({"quality": "1080p"},
                                [link(id=1, is_resumable=0)])
        two = tiers.for_release({"quality": "1080p"},
                                [link(id=2, is_resumable=1)])
        three = tiers.for_release({"quality": "480p"}, [link(id=3)])
        merged = tiers.merge([one, two, three])
        self.assertEqual([tier["band"] for tier in merged["tiers"]],
                         ["1080p", "480p"])
        self.assertEqual(merged["tiers"][0]["link"]["id"], 2)
        self.assertEqual(merged["tiers"][0]["copies"], 2)
        self.assertEqual(merged["auto"]["band"], "1080p")

    def test_auto_picks_a_playable_band_over_a_download_only_one(self):
        hd = tiers.for_release({"quality": "1080p"},
                               [link(id=1, playback_type="iframe")])
        sd = tiers.for_release({"quality": "720p"}, [link(id=2)])
        merged = tiers.merge([hd, sd])
        self.assertEqual(merged["auto"]["band"], "720p")
        self.assertEqual(merged["download_only_bands"], ["1080p"])

    def test_mixed_type_season_and_episode_keys_sort_without_raising(self):
        # Scrapers write these columns as text as often as numbers, and a tuple
        # sort of ("1", 1) is how this crashed against the real catalog.
        pairs = [(None, None), ("2", 3), (1, "4"), ("Season 7", 2)]
        ordered = sorted(pairs, key=lambda p: tiers.scope_sort_key(*p))
        self.assertEqual(ordered,
                         [(None, None), (1, "4"), ("2", 3), ("Season 7", 2)])
        self.assertTrue(sorted((tiers.scope_sort_key(*p) for p in pairs)))
        # A movie (no season at all) comes before any season, and a season with
        # no number in it comes after every season that has one.
        self.assertLess(tiers.scope_sort_key(None, None), tiers.scope_sort_key("1", "1"))
        self.assertLess(tiers.scope_sort_key("9", 1), tiers.scope_sort_key("Extras", 1))


class PublicShapeTests(unittest.TestCase):
    """`link_view` is the only door a `download_sources` row has to the public."""

    def setUp(self):
        self.secret = patch.object(viewer, "signing_secret", return_value="test-secret")
        self.secret.start()
        self.addCleanup(self.secret.stop)

    def test_the_public_kind_uses_our_words_not_the_scraper_s(self):
        for playback_type, kind in (("direct", "direct"), ("url", "resolve"),
                                    ("download", "download"), ("iframe", "external")):
            view = viewer.link_view(link(playback_type=playback_type), "http://our.box")
            self.assertEqual(view["kind"], kind, playback_type)

    def test_the_word_embed_never_reaches_a_response(self):
        # "embed" is a hoster name in this ledger (`service = 'embed'`), so a
        # sentinel scan treats it as provenance and our own vocabulary must not
        # collide with it.
        view = viewer.link_view(link(playback_type="iframe"), "http://our.box")
        self.assertNotIn("embed", str(view).lower())
        for key in redact.PROVENANCE:
            self.assertNotIn(key, view)

    def test_every_public_key_of_a_tier_is_ours(self):
        tier = tiers.for_release({"quality": "720p"},
                                 [viewer.link_view(link(), "http://our.box")])
        blob = str(tier).lower()
        for needle in ("cdn.example", "site", "service", "pixeldrain", "hubcloud"):
            self.assertNotIn(needle, blob, needle)


class DetailRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "tiers.db"
        for target, value in ((fast_fetch, "DB_PATH"), (viewer, "DB_PATH")):
            patcher = patch.object(target, value, self.db_path)
            patcher.start()
            self.addCleanup(patcher.stop)
        cinemeta = patch.object(fast_fetch, "fetch_cinemeta_metadata", return_value=None)
        cinemeta.start()
        self.addCleanup(cinemeta.stop)
        fast_fetch.init_db()

    def tearDown(self):
        self.temp_dir.cleanup()

    def _save(self, quality, sources):
        media = {
            "url": "https://site-a.example/film/", "slug": "film",
            "title": "Example Film (2024)", "clean_title": "Example Film", "year": 2024,
            "content_type": "movie", "seasons": None, "poster_url": None,
            "backdrop_urls": None, "imdb_rating": None, "genres": None,
            "synopsis": None, "is_18_plus": 0, "is_animated": 0,
            "source_site": "site_a", "industry": "Hollywood", "country": "USA",
            "language": "English",
            "canonical_key": fast_fetch.generate_canonical_key("Example Film", 2024),
            "releases": [{"release_title": f"Example Film {quality}", "quality": quality,
                          "codec": "x264", "size": "1GB", "languages": "English",
                          "season": None, "episode": None,
                          "intermediate_url": "https://site-a.example/release",
                          "sources": sources}],
        }
        return fast_fetch.save_scraped_data(media)

    def test_the_detail_route_hands_back_one_option_per_band(self):
        post_id = self._save("1080p", [
            {"source_name": "Mirror One", "service": "hubcloud_10g",
             "resource_id": "a", "source_url": "https://a.example/1",
             "final_url": "https://cdn.example/a", "is_temporary": 0},
            {"source_name": "Mirror Two", "service": "pixeldrain",
             "resource_id": "b", "source_url": "https://b.example/2",
             "final_url": "https://cdn.example/b", "is_temporary": 0},
        ])
        viewer.DB_PATH = self.db_path
        detail = viewer.api_v1_get_post_detail(post_id, base_url="http://our.box")
        self.assertTrue(detail, "detail route returned nothing")
        groups = detail["option_groups"]
        self.assertEqual(len(groups), 1)
        tiers_offered = groups[0]["tiers"]
        self.assertEqual([tier["band"] for tier in tiers_offered], ["1080p"])
        self.assertEqual(tiers_offered[0]["copies"], 2)
        handle = tiers_offered[0]["link"]["stream_id"]
        self.assertTrue(handle and "/" not in handle)
        # The player keys on an opaque handle, not on an enumerable row id.
        self.assertNotIn("link_id", tiers_offered[0]["link"])
        self.assertFalse(handle.isdigit())
        self.assertIsInstance(redact.parse_token(handle, viewer.signing_secret()), int)
        blob = str(detail).lower()
        for needle in ("hubcloud", "pixeldrain", "site_a", "vegamovies", "cdn.example"):
            self.assertNotIn(needle, blob, needle)
        for release in detail["releases"]:
            self.assertIn(release["band"], set(tiers.BANDS) | {tiers.UNSPECIFIED})
            self.assertTrue(release["quality_label"])


if __name__ == "__main__":
    unittest.main()
