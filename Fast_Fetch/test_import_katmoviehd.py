#!/usr/bin/env python3
"""
Product-level tests for the KatMovieHD media-type / year identity fix.

Every fixture in here is a real page title harvested from the live staging
database (/home/ubuntu/radd-stream-data/katmoviehd.db) that the old parser got
wrong.  The old parser:

  * read a season out of an apostrophe-s or a sequel number
    ("Five Nights at Freddy's 2" -> season 2, "It's 1999" -> season 1999),
  * let a year inside the title beat the parenthesised release year
    ("Hijack 1971 (2024)" -> 1971),
  * typed a film as a series whenever the word "episode" appeared anywhere in
    the page HTML — including inside the synopsis prose,

which is what produced the 1,603 "External media ID matches a record with a
different media type" rows in `merge_conflicts`.

Tests assert the ingested values (title, year, media type, season, canonical
key) and the ledger/projection output — never the regexes that produce them.
Nothing here touches a database outside a temporary directory.
"""

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import catalog_v2
import fast_fetch
import import_katmoviehd
import merge_catalogs


def derive(fixture):
    """Runs the real identity ladder over one fixture row."""
    return import_katmoviehd.derive_katmoviehd_identity(
        fixture["raw"],
        slug=fixture.get("slug", ""),
        categories=fixture.get("categories"),
        page_categories=fixture.get("page_categories"),
        page_field=fixture.get("page_field"),
        has_episode_releases=fixture.get("has_episode_releases"),
    )


def observed(identity):
    """The five ingested fields a reviewer cares about, as one comparable dict."""
    return {
        "title": identity["title"],
        "year": identity["year"],
        "media_type": identity["media_type"],
        "season": identity["season"],
        "canonical_key": identity["canonical_key"],
    }


# ── Real scraped pages the old parser poisoned ───────────────────────────────
#
# `raw` is the `original_title` exactly as the crawler stored it (the site
# publishes the ampersand as an HTML entity), `slug` is the real page slug and
# `categories` is the real API category list.
PATHOLOGICAL = [
    {
        "name": "sequel number is not a season",
        "slug": "five-nights-at-freddys-2-2025-hindi",
        "raw": "Five Nights at Freddy's 2 (2025) Hindi Dubbed (DD 5.1) &amp; English "
               "[Dual Audio] WEB-DL 1080p 720p 480p HD [Full Movie]",
        "categories": ["dual-audio", "dubbed-movie", "horror", "mystery", "thriller"],
        # old parser: title "Five Nights at Freddy's 2", season 2, series,
        #             key five-nights-at-freddy-s-2_s2
        "expect": {
            "title": "Five Nights at Freddy's 2",
            "year": 2025,
            "media_type": "movie",
            "season": None,
            "canonical_key": "five-nights-at-freddys-2_2025",
        },
    },
    {
        "name": "apostrophe-s year in title is not a season",
        "slug": "lets-murder-like-its-1999-2026-hindi-dubbed-webrip-1xbet",
        "raw": "Lets Murder Like Its 1999 (2026) Full Movie In Hindi Dubbed "
               "[WEBRip 1080p 720p 480p] - 1XBET",
        "categories": ["adventure", "comedy", "unofficial-dubbed", "animation"],
        # old parser: year 1999, clean title carried the 1XBET affiliate junk
        "expect": {
            "title": "Lets Murder Like Its 1999",
            "year": 2026,
            "media_type": "movie",
            "season": None,
            "canonical_key": "lets-murder-like-its-1999_2026",
        },
    },
    {
        "name": "the two dubbed pages of one film share one identity",
        "slug": "lets-murder-like-its-1999-2026-webrip-tel",
        "raw": "Let's Murder Like It's 1999! (2026) Full Movie in Telugu Dubbed "
               "[WEBRip 1080p 720p 480p] - 1XBET",
        "categories": ["drama", "thriller", "telugu-dubbed-vo"],
        # old parser: season 1999, key let-s-murder-like-it-s-1999-in-1xbet_s1999
        "expect": {
            "title": "Let's Murder Like It's 1999",
            "year": 2026,
            "media_type": "movie",
            "season": None,
            "canonical_key": "lets-murder-like-its-1999_2026",
        },
    },
    {
        "name": "parenthesised year beats the title year (Spielberg's 1941)",
        "slug": "1941-1979-hindi",
        "raw": "1941 (1979) [Directors Cut] Hindi Dubbed (ORG) &amp; English [Dual Audio] "
               "BluRay 1080p 720p 480p HD [Full Movie]",
        "categories": ["action", "comedy", "dual-audio", "dubbed-movie", "war"],
        # old parser: year 1941, key 1941_1941
        "expect": {
            "title": "1941",
            "year": 1979,
            "media_type": "movie",
            "season": None,
            "canonical_key": "1941_1979",
        },
    },
    {
        "name": "numeric title survives the noise stripper",
        "slug": "1911-2024-hindi",
        "raw": "1911 (2011) [Full Movie] Hindi Dubbed (ORG) & Chinese [Dual Audio] "
               "BluRay 1080p 720p 480p HD",
        "categories": ["drama", "dual-audio", "dubbed-movie", "history", "war"],
        "expect": {
            "title": "1911",
            "year": 2011,
            "media_type": "movie",
            "season": None,
            "canonical_key": "1911_2011",
        },
    },
    {
        "name": "year in title is part of the name, not the release year",
        "slug": "hijack-1971-2024-hindi",
        "raw": "Hijack 1971 (2024) Hindi Dubbed (DD 5.1) &amp; Korean [Dual Audio] "
               "WEB-DL 1080p 720p 480p HD [Full Movie]",
        "categories": ["action", "crime", "dual-audio", "dubbed-movie", "thriller"],
        "expect": {
            "title": "Hijack 1971",
            "year": 2024,
            "media_type": "movie",
            "season": None,
            "canonical_key": "hijack-1971_2024",
        },
    },
    {
        "name": "a title that IS an S-number is not a season",
        "slug": "s86-2026-webrip-bengali",
        "raw": "S86 (2026) Full Movie in Bengali Dubbed [WEBRip 1080p 720p 480p] - 1XBET",
        "categories": ["horror", "thriller", "bengali-dubbed-unofficial"],
        # old parser: series, key in-bengali-1xbet_s86 (title text lost entirely)
        "expect": {
            "title": "S86",
            "year": 2026,
            "media_type": "movie",
            "season": None,
            "canonical_key": "s86_2026",
        },
    },
    {
        "name": "unconfirmed bare S-token stays in the title",
        "slug": "romeo-s3-2025-hin-webrip-ads",
        "raw": "Romeo S3 (2025) Full Movie In Hindi Dubbed (Unofficial) "
               "[WEBRip 1080p 720p 480p] - #ADs",
        "categories": ["action", "4rabet"],
        # old parser: season 3, series, key romeo-in-unofficial-ads_s3
        "expect": {
            "title": "Romeo S3",
            "year": 2025,
            "media_type": "movie",
            "season": None,
            "canonical_key": "romeo_2025",
        },
    },
    {
        "name": "a language inside the title is not noise",
        "slug": "the-bus-a-french-football-mutiny-2026-hindi",
        "raw": "The Bus: A French Football Mutiny (2026) Hindi Dubbed (DD 5.1) &amp; English "
               "[Dual Audio] WEB-DL 1080p 720p 480p HD [Full Movie]",
        "categories": ["documentary", "dual-audio", "dubbed-movie"],
        # old parser: media_type series (the word "episode" appears in the synopsis)
        "expect": {
            "title": "The Bus A French Football Mutiny",
            "year": 2026,
            "media_type": "movie",
            "season": None,
            "canonical_key": "the-bus-a-french-football-mutiny_2026",
        },
    },
    {
        "name": "year glued to a marker inside the parenthesis",
        "slug": "the-life-of-chuck-2024",
        "raw": "The Life of Chuck (2025 Full Movie) WEB-DL 1080p 720p 480p [HD x264 &amp; HEVC] "
               "(In English 5.1 DD) + ESubs",
        "categories": ["drama", "fantasy", "sci-fi"],
        # old parser: key the-life-of-chuck-2025-in-5-1-dd_2025
        "expect": {
            "title": "The Life of Chuck",
            "year": 2025,
            "media_type": "movie",
            "season": None,
            "canonical_key": "the-life-of-chuck_2025",
        },
    },
    {
        "name": "the [18+] annotation is stripped but does not invent a series",
        "slug": "the-key-game",
        "raw": "[18+] The Key Game (2022) Hindi Dubbed (ORG) & Spanish [Dual Audio] "
               "WEB-DL 1080p 720p 480p HD [Full Movie]",
        "categories": ["adult", "comedy", "dual-audio", "dubbed-movie"],
        # old parser: series, key the-key-game-spanish_2022
        "expect": {
            "title": "The Key Game",
            "year": 2022,
            "media_type": "movie",
            "season": None,
            "canonical_key": "the-key-game_2022",
        },
    },
    {
        "name": "roman-numeral episode stays in the title",
        "slug": "star-wars-episode-vi-return-of-the-jedi-1983-dual-audio-brrip-720p-hindi-eng-download",
        "raw": "Star Wars Episode VI Return of the Jedi (1983) BluRay 720p 480p "
               "Dual Audio (Hindi Dubbed + English) Esubs .",
        "categories": ["action", "adventure", "dual-audio", "dubbed-movie", "fantasy", "sci-fi"],
        # old parser: media_type series, title "Star Wars VI Return of the Jedi"
        "expect": {
            "title": "Star Wars Episode VI Return of the Jedi",
            "year": 1983,
            "media_type": "movie",
            "season": None,
            "canonical_key": "star-wars-episode-vi-return-of-the-jedi_1983",
        },
    },
    {
        "name": "no usable type evidence stays UNKNOWN",
        "slug": "after-we-collided-2020-hindi-1xbet",
        "raw": "After We Collided (2020) Hindi (Unofficial Dubbed) + English (ORG) "
               "[Dual Audio] WebRip 720p [1XBET]",
        "categories": ["unofficial-dubbed"],
        # old parser: series, title "After We Collided + WebRip"
        "expect": {
            "title": "After We Collided",
            "year": 2020,
            "media_type": None,
            "season": None,
            "canonical_key": "after-we-collided_2020",
        },
    },
    {
        "name": "season word plus episode-added marker is a real season",
        "slug": "pretty-little-liars-s02-2024",
        "raw": "Pretty Little Liars: Summer School [Season 2] Hindi Dubbed (ORG) [Dual Audio] "
               "1080p 720p 480p {TV Series} \u2013 S2 All Episodes",
        "categories": ["drama", "dual-audio", "horror", "mystery", "tv-series-dubbed", "hbo-max"],
        # old parser: key pretty-little-liars-summer-school-tv-all_s2
        "expect": {
            "title": "Pretty Little Liars Summer School",
            "year": 2024,
            "media_type": "series",
            "season": 2,
            "canonical_key": "pretty-little-liars-summer-school_s2",
        },
    },
    {
        "name": "zero-padded S-token corroborated by All Episodes",
        "slug": "taxi-driver-2021-s01-hindi",
        "raw": "Taxi Driver (2021) S01 Hindi Dubbed (ORG) & Korean [Dual Audio] WEB-DL "
               "1080p 720p 480p HD [K-Drama Series] \u2013 [All Episodes Added]",
        "categories": ["action", "adventure", "crime", "dual-audio", "thriller", "korean-drama"],
        "expect": {
            "title": "Taxi Driver",
            "year": 2021,
            "media_type": "series",
            "season": 1,
            "canonical_key": "taxi-driver_s1",
        },
    },
    {
        "name": "season 3 of a show whose title also carries a season token",
        "slug": "the-white-lotus-2025-s03-hindi",
        "raw": "The White Lotus (Season 3) Hindi Dubbed [Dual Audio] 4K-2160p UHD / "
               "1080p 720p 480p HD SDR [HBO Series]  [S3 Episode 8 Added]",
        "categories": ["comedy", "drama", "dual-audio", "tv-series-dubbed"],
        "expect": {
            "title": "The White Lotus",
            "year": 2025,
            "media_type": "series",
            "season": 3,
            "canonical_key": "the-white-lotus_s3",
        },
    },
    {
        "name": "two seasons of one show keep one title and distinct keys",
        "slug": "mobland-s1-hindi",
        "raw": "MobLand (Season 1) Hindi Dubbed (DD 5.1) &amp; English [Dual Audio] All Episodes "
               "| WEB-DL 2160p 1080p 720p 480p HDR/DV [2025 Paramount+ Series]",
        "categories": ["crime", "drama", "dual-audio", "tv-series-dubbed", "hindi-dubbed"],
        # old parser: key mobland-all_s1 (the word "All" leaked into the identity)
        "expect": {
            "title": "MobLand",
            "year": 2025,
            "media_type": "series",
            "season": 1,
            "canonical_key": "mobland_s1",
        },
    },
    {
        "name": "same show, next season",
        "slug": "mobland-s2-hindi",
        "raw": "MobLand (Season 2) Hindi Dubbed (ORG) &amp; English [Dual Audio] | WEB-DL 4K 2160p "
               "1080p 720p 480p HD [2026 Paramount+ Series] [Episode 05 Added]",
        "categories": ["crime", "drama", "dual-audio", "hindi-dubbed", "tv-series-dubbed"],
        "expect": {
            "title": "MobLand",
            "year": 2026,
            "media_type": "series",
            "season": 2,
            "canonical_key": "mobland_s2",
        },
    },
    {
        "name": "complete-season page without any year on the page",
        "slug": "the-punisher-season-2",
        "raw": "Marvels The Punisher S02 Season 2 Complete 480p 720p 1080p HDRip "
               "| All Episodes | Netflix",
        "categories": ["action", "adventure", "complete-season", "crime", "tv-shows"],
        # old parser: title "Marvels The Punisher S02"
        "expect": {
            "title": "Marvels The Punisher",
            "year": None,
            "media_type": "series",
            "season": 2,
            "canonical_key": "marvels-the-punisher_s2",
        },
    },
    {
        "name": "episode-count marker corroborates an unconfirmed S-token",
        "slug": "gots08",
        "raw": "Game Of Thrones Season 8 [Hindi Dub (Voice Over)] Complete 480p 720p / 1080p HD "
               "[GOT S8 Episode 6 Added]",
        "categories": ["tv-series-dubbed", "unofficial-dubbed"],
        # old parser: title "Game Of Thrones /"
        "expect": {
            "title": "Game Of Thrones",
            "year": None,
            "media_type": "series",
            "season": 8,
            "canonical_key": "game-of-thrones_s8",
        },
    },
]

# Pages the old parser already got right — the fix must not move them.
REGRESSIONS = [
    {
        "name": "plain dubbed movie",
        "slug": "the-campaign-2012-hindi",
        "raw": "The Campaign (2012) Hindi Dubbed (ORG) &amp; English [Dual Audio] BluRay "
               "1080p 720p 480p HD [Full Movie]",
        "categories": ["comedy", "dual-audio", "dubbed-movie"],
        "expect": {
            "title": "The Campaign",
            "year": 2012,
            "media_type": "movie",
            "season": None,
            "canonical_key": "the-campaign_2012",
        },
    },
    {
        "name": "4K multi-audio movie",
        "slug": "colony-2026-hindi",
        "raw": "Colony (2026) Hindi Dubbed (ORG) &amp; Korean [Dual Audio] BluRay 4K 2160p "
               "1080p 720p 480p SDR [Full Movie]",
        "categories": ["action", "adventure", "crime", "dual-audio", "hindi-dubbed"],
        "expect": {
            "title": "Colony",
            "year": 2026,
            "media_type": "movie",
            "season": None,
            "canonical_key": "colony_2026",
        },
    },
    {
        "name": "sequel film sharing a franchise name",
        "slug": "five-nights-at-freddys-2023-hin",
        "raw": "Five Nights at Freddy's (2023) Hindi Dubbed (ORG 5.1) & English [Dual Audio] "
               "WEBRip 1080p 720p 480p HD [Full Movie]",
        "categories": ["dual-audio", "dubbed-movie", "horror", "mystery", "thriller"],
        "expect": {
            "title": "Five Nights at Freddy's",
            "year": 2023,
            "media_type": "movie",
            "season": None,
            "canonical_key": "five-nights-at-freddys_2023",
        },
    },
    {
        "name": "remastered classic does not collide with the modern series",
        "slug": "taxi-driver-1976-hindi",
        "raw": "Taxi Driver (1976) Remastered Hindi Dubbed (DD 5.1) &amp; English [Dual Audio] "
               "BluRay 1080p 720p 480p [Full Movie]",
        "categories": ["crime", "drama", "dual-audio", "dubbed-movie"],
        "expect": {
            "title": "Taxi Driver Remastered",
            "year": 1976,
            "media_type": "movie",
            "season": None,
            "canonical_key": "taxi-driver-remastered_1976",
        },
    },
    {
        "name": "horror remake is not the 2026 film of a similar name",
        "slug": "the-last-house-on-the-left",
        "raw": "[18+] The Last House on the Left (2009) BluRay 720p 480p Dual Audio "
               "[Hindi Dubbed + English] [Full Movie]",
        "categories": ["dual-audio", "dubbed-movie", "horror", "thriller"],
        "expect": {
            "title": "The Last House on the Left",
            "year": 2009,
            "media_type": "movie",
            "season": None,
            "canonical_key": "the-last-house-on-the-left_2009",
        },
    },
    {
        "name": "download-prefixed movie page",
        "slug": "the-last-house-2026-hindi",
        "raw": "The Last House (2026) Hindi Dubbed (DD 5.1) &amp; English [Dual Audio] WEB-DL "
               "2160p 1080p 720p 480p 4K HD [Full Movie]",
        "categories": ["action", "dual-audio", "dubbed-movie", "horror", "mystery", "sci-fi"],
        "expect": {
            "title": "The Last House",
            "year": 2026,
            "media_type": "movie",
            "season": None,
            "canonical_key": "the-last-house_2026",
        },
    },
    {
        # Regression for the season-2 page of the same show (existing suite data).
        "name": "series page whose run-years are inside a bracketed annotation",
        "slug": "the-punisher-s02-2017",
        "raw": "The Punisher (Season 2) Hindi Dubbed (DD 5.1) &amp; English [Dual Audio] "
               "| WEB-DL 1080p 720p 480p HD [2017\u20132019 Marvel Series] [Episode 04 Added]",
        "categories": ["action", "complete-season", "tv-series-dubbed"],
        "expect": {
            "title": "The Punisher",
            "year": 2017,
            "media_type": "series",
            "season": 2,
            "canonical_key": "the-punisher_s2",
        },
    },
]


class RealScrapedTitleTests(unittest.TestCase):
    """Every poisoned page from the live staging DB, asserted field by field."""

    def _check(self, fixture):
        identity = derive(fixture)
        self.assertEqual(
            observed(identity), fixture["expect"],
            f"{fixture['name']} ({fixture['slug']})",
        )
        self.assertTrue(identity["evidence"]["type"], "type evidence must be recorded")
        self.assertTrue(identity["evidence"]["year"], "year evidence must be recorded")
        self.assertTrue(identity["evidence"]["season"], "season evidence must be recorded")

    def test_pathological_pages(self):
        self.assertGreaterEqual(len(PATHOLOGICAL), 12, "need the harvested fixtures")
        for fixture in PATHOLOGICAL:
            with self.subTest(**{"fixture": fixture["name"]}):
                self._check(fixture)

    def test_previously_correct_pages_stay_correct(self):
        for fixture in REGRESSIONS:
            with self.subTest(**{"fixture": fixture["name"]}):
                self._check(fixture)

    def test_headline_freddy_sequel_is_a_movie(self):
        fixture = next(f for f in PATHOLOGICAL if f["slug"].startswith("five-nights-at-freddys-2"))
        identity = derive(fixture)
        self.assertIsNone(identity["season"])
        self.assertEqual(identity["media_type"], "movie")
        self.assertNotIn("_s", identity["canonical_key"])

    def test_both_apostrophe_spellings_of_one_film_agree(self):
        """The Hindi and Telugu pages of one film must share one identity key."""
        hindi = derive(next(f for f in PATHOLOGICAL
                            if f["slug"] == "lets-murder-like-its-1999-2026-hindi-dubbed-webrip-1xbet"))
        telugu = derive(next(f for f in PATHOLOGICAL
                             if f["slug"] == "lets-murder-like-its-1999-2026-webrip-tel"))
        self.assertEqual(hindi["canonical_key"], telugu["canonical_key"])
        self.assertEqual(hindi["year"], telugu["year"])
        self.assertEqual(hindi["media_type"], telugu["media_type"])

    def test_unknown_is_never_a_guess(self):
        """A page with no type evidence reports None instead of picking a family."""
        fixture = next(f for f in PATHOLOGICAL if f["slug"] == "after-we-collided-2020-hindi-1xbet")
        identity = derive(fixture)
        self.assertIsNone(identity["media_type"])
        self.assertEqual(identity["evidence"]["type"], "no-type-evidence")

    def test_no_key_is_degenerate(self):
        """A key that is only a year suffix would collide with every other such row."""
        for fixture in PATHOLOGICAL + REGRESSIONS:
            with self.subTest(**{"fixture": fixture["slug"]}):
                key = derive(fixture)["canonical_key"]
                self.assertTrue(key)
                self.assertNotEqual(key, "unknown")
                self.assertFalse(key.startswith("_"), key)


class EvidencePrecedenceTests(unittest.TestCase):
    """The ladder: page field > category path > API categories > title > releases > slug."""

    MOVIE_SERIES_TITLE = "Some Show (Season 2) Complete All Episodes TV Series Full Movie"

    def test_page_field_beats_title_text(self):
        identity = import_katmoviehd.derive_katmoviehd_identity(
            self.MOVIE_SERIES_TITLE, page_field="movie")
        self.assertEqual(identity["media_type"], "movie")
        self.assertEqual(identity["evidence"]["type"], "page-field-label:Movie Name")

    def test_page_field_series_beats_movie_marker(self):
        identity = import_katmoviehd.derive_katmoviehd_identity(
            "Some Film (2020) Full Movie", page_field="series")
        self.assertEqual(identity["media_type"], "series")

    def test_conflicting_page_field_falls_through_to_taxonomy(self):
        identity = import_katmoviehd.derive_katmoviehd_identity(
            "Some Show (2019) Full Movie", page_field="conflict", categories=["tv-series"])
        self.assertEqual(identity["media_type"], "series")
        self.assertTrue(identity["evidence"]["type"].startswith("api-category-list"))

    def test_conflicting_category_path_reports_unknown_not_a_coin_flip(self):
        identity = import_katmoviehd.derive_katmoviehd_identity(
            "Ambiguous Thing (2019)", page_categories=["movies", "tv-series"])
        self.assertIsNone(identity["media_type"])
        self.assertTrue(identity["evidence"]["type"].startswith("conflicting-page-category-path"))

    def test_conflicting_api_categories_report_unknown(self):
        identity = import_katmoviehd.derive_katmoviehd_identity(
            "Ambiguous Thing (2019)", categories=["dubbed-movie", "complete-season"])
        self.assertIsNone(identity["media_type"])
        self.assertTrue(identity["evidence"]["type"].startswith("conflicting-api-category-list"))

    def test_taxonomy_beats_title_text(self):
        """A page filed under a movie category is a movie even if its title says 'Season 2'."""
        identity = import_katmoviehd.derive_katmoviehd_identity(
            "Compilation Season 2 (2018)", categories=["dubbed-movie"])
        self.assertEqual(identity["media_type"], "movie")
        self.assertTrue(identity["evidence"]["type"].startswith("api-category-list"))

    def test_title_tie_descends_to_episode_releases(self):
        identity = import_katmoviehd.derive_katmoviehd_identity(
            "Dark Legacy (2020) Season 2 Full Movie", has_episode_releases=True)
        self.assertEqual(identity["media_type"], "series")
        self.assertEqual(identity["evidence"]["type"], "episode-structured-releases")

    def test_title_tie_descends_to_slug_then_stays_unknown(self):
        tied = "Dark Legacy (2020) Season 2 Full Movie"
        by_slug = import_katmoviehd.derive_katmoviehd_identity(
            tied, slug="dark-legacy-2020-full-movie")
        self.assertEqual(by_slug["media_type"], "movie")
        self.assertEqual(by_slug["evidence"]["type"], "slug-marker")

        nothing = import_katmoviehd.derive_katmoviehd_identity(tied)
        self.assertIsNone(nothing["media_type"])
        self.assertTrue(nothing["evidence"]["type"].startswith("conflicting-title-evidence"))

    def test_anime_category_is_not_series_evidence(self):
        identity = import_katmoviehd.derive_katmoviehd_identity(
            "Ne Zha 2 (2025) Full Movie", categories=["anime"])
        self.assertEqual(identity["media_type"], "movie")
        self.assertIsNone(identity["season"])

    def test_categories_accept_stored_json_text(self):
        """A re-derive reads the staging DB, where genres are stored as JSON text."""
        identity = import_katmoviehd.derive_katmoviehd_identity(
            "The Bus: A French Football Mutiny (2026) Hindi Dubbed (DD 5.1) &amp; English "
            "[Dual Audio] WEB-DL 1080p 720p 480p HD [Full Movie]",
            categories=json.dumps(["documentary", "dual-audio", "dubbed-movie"]))
        self.assertEqual(identity["media_type"], "movie")

    def test_year_precedence_parenthesis_slug_title_then_run(self):
        cases = [
            ({"raw_title": "Hijack 1971 (2024) Full Movie"}, 2024, "title-parenthesis-year"),
            ({"raw_title": "Some Film", "slug": "some-film-2019-hindi"}, 2019, "slug-year"),
            ({"raw_title": "Hijack 1971"}, 1971, "title-single-year"),
            ({"raw_title": "Shogun 2017\u20132019 Revival"}, 2017, "title-year-run"),
            ({"raw_title": "No Year Here"}, None, "year-unknown"),
        ]
        for kwargs, expected_year, expected_evidence in cases:
            with self.subTest(**{"title": kwargs["raw_title"]}):
                identity = import_katmoviehd.derive_katmoviehd_identity(**kwargs)
                self.assertEqual(identity["year"], expected_year)
                self.assertEqual(identity["evidence"]["year"], expected_evidence)

    def test_bracketed_run_of_years_is_read_as_the_start_year(self):
        identity = import_katmoviehd.derive_katmoviehd_identity(
            "The Punisher (Season 2) [2017\u20132019 Marvel Series]")
        self.assertEqual(identity["year"], 2017)

    def test_slug_release_year_beats_a_year_that_is_part_of_the_title(self):
        """
        'Bengal 1947' is the film's name; the 2022 in its slug is its release year.
        """
        identity = import_katmoviehd.derive_katmoviehd_identity(
            "Bengal 1947", slug="bengal-1947-2022-tamil-dubbed")
        self.assertEqual(identity["year"], 2022)
        self.assertEqual(identity["evidence"]["year"], "slug-year-not-in-title")
        self.assertEqual(identity["title"], "Bengal 1947")

    def test_two_unresolvable_slug_years_stay_unknown(self):
        identity = import_katmoviehd.derive_katmoviehd_identity(
            "Bengal 1947 2022", slug="bengal-1947-2022")
        self.assertIsNone(identity["year"], "refusing to guess beats guessing wrong")
        self.assertEqual(identity["evidence"]["year"], "slug-year-ambiguous")

    def test_future_announcement_years_are_plausible_but_not_impossible_values(self):
        identity = import_katmoviehd.derive_katmoviehd_identity("Colony (2026) Full Movie")
        self.assertEqual(identity["year"], 2026)
        impossible = import_katmoviehd.derive_katmoviehd_identity("Movie (1899) Full Movie")
        self.assertIsNone(impossible["year"])


class TitleNoiseTests(unittest.TestCase):
    """Affiliate/promo junk never reaches a clean title or an identity key."""

    JUNK = ("1xbet", "1XBET", "4rabet", "#ADs", "Online Stream", "Unofficial", "Subtitles")

    def test_promo_junk_absent_from_every_fixture_title(self):
        for fixture in PATHOLOGICAL + REGRESSIONS:
            with self.subTest(**{"fixture": fixture["slug"]}):
                lowered = derive(fixture)["title"].lower()
                for junk in self.JUNK:
                    self.assertNotIn(junk.lower(), lowered)

    def test_promo_junk_absent_from_every_fixture_key(self):
        for fixture in PATHOLOGICAL + REGRESSIONS:
            with self.subTest(**{"fixture": fixture["slug"]}):
                key = derive(fixture)["canonical_key"].lower()
                for junk in self.JUNK:
                    self.assertNotIn(junk.lower().strip("#"), key)

    def test_language_names_survive_when_they_are_the_title(self):
        identity = import_katmoviehd.derive_katmoviehd_identity(
            "The French Dispatch (2021) Full Movie In English Subtitles",
            slug="the-french-dispatch-2021")
        self.assertEqual(identity["title"], "The French Dispatch")

    def test_title_is_never_empty_and_never_only_the_year(self):
        for raw, slug in (
            ("(2025) Full Movie", "full-movie-2025"),
            ("1XBET", "1xbet"),
            ("Download", "download"),
            ("", "untitled-page"),
        ):
            with self.subTest(**{"raw": raw, "slug": slug}):
                identity = import_katmoviehd.derive_katmoviehd_identity(raw, slug=slug)
                self.assertTrue(identity["title"])
                self.assertNotEqual(identity["title"].strip(), str(identity["year"] or ""))
                self.assertTrue(identity["canonical_key"])

    def test_a_real_parenthetical_subtitle_survives_the_cleaner(self):
        """Only annotation-shaped noise is dropped; "Or: How I Learned…" is the title."""
        identity = import_katmoviehd.derive_katmoviehd_identity(
            "Dr. Strangelove (Or: How I Learned to Stop Worrying)", slug="dr-strangelove")
        self.assertIn("Strangelove", identity["title"])
        self.assertIn("Stop Worrying", identity["title"])


class LegacyContractTests(unittest.TestCase):
    """The old four-value contract keeps working for callers that cannot supply evidence."""

    def test_wrapper_still_returns_the_four_tuple(self):
        clean, year, season, key = import_katmoviehd.clean_katmoviehd_title(
            "Five Nights at Freddy's 2 (2025) Hindi Dubbed (DD 5.1) &amp; English "
            "[Dual Audio] WEB-DL 1080p 720p 480p HD [Full Movie]")
        self.assertEqual(clean, "Five Nights at Freddy's 2")
        self.assertEqual(year, 2025)
        self.assertIsNone(season)
        self.assertEqual(key, "five-nights-at-freddys-2_2025")

    def test_clean_katmoviehd_title_is_reachable_by_its_old_name(self):
        self.assertTrue(callable(import_katmoviehd.clean_katmoviehd_title))


# ── Ingested output: staging rows, ledger merge, projection ─────────────────

FREE_NIGHTS = next(f for f in PATHOLOGICAL if f["slug"] == "five-nights-at-freddys-2-2025-hindi")
FREE_NIGHTS_IMDB = "tt30274401"

# What the pre-fix parser wrote for that same page, kept here so the tests can
# prove the conflict really came from the bug and really goes away after it.
LEGACY_FIVE_NIGHTS = {
    "title": "Five Nights at Freddy's 2",
    "year": 2025,
    "media_type": "series",
    "canonical_key": "five-nights-at-freddy-s-2_s2",
}


def release_for(label, resolution, size_bytes, resource_id, season=None, episode=None):
    return {
        "label": label,
        "quality": resolution,
        "resolution": resolution,
        "size_bytes": size_bytes,
        "season_number": season,
        "episode_number": episode,
        "audio_languages": json.dumps(["Hindi", "English"]),
        "codec": "x264",
        "bridge_url": f"https://links.kmhd.me/file/{resource_id}",
        "sources": [
            {
                "source_name": f"HubCloud [{resource_id}]",
                "service": "fsl_r2",
                "resource_id": resource_id,
                "source_url": f"https://hubcloud.ist/drive/{resource_id}",
                "final_url": f"https://r2.example/{resource_id}",
                "is_temporary": 0,
                "quality": resolution,
                "playback_type": "url",
            }
        ],
    }


class StagingRowTests(unittest.TestCase):
    """What the importer actually writes into the per-site staging database."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.db_path = Path(self.temp_dir.name) / "katmoviehd.db"
        import_katmoviehd.init_staging_db(self.db_path)

    def save(self, fixture, imdb_id="tt0000001", extra_releases=()):
        identity = derive(fixture)
        releases = [release_for("720p Links [821MB]", "720p", 861150158, "rel1")]
        releases.extend(extra_releases)
        post_data = {
            "canonical_key": identity["canonical_key"],
            "title": identity["title"],
            "original_title": fixture["raw"],
            "year": identity["year"],
            "media_type": identity["media_type"],
            "imdb_id": imdb_id,
            "poster_url": "https://image.tmdb.org/t/p/w500/test.jpg",
            "synopsis": "A synopsis that happens to use the word episode.",
            "genres": json.dumps(fixture.get("categories") or []),
            "rating": 6.4,
            "site": "katmoviehd",
            "post_url": f"https://new.katmoviehd.top/{fixture['slug']}",
            "releases": releases,
        }
        self.assertTrue(import_katmoviehd.save_post_to_staging_db(self.db_path, post_data))
        return identity

    def read(self, key):
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM posts WHERE canonical_key = ?", (key,)).fetchone()
            if row is None:
                self.fail(f"no staging row for {key}")
            releases = conn.execute(
                "SELECT r.*, (SELECT COUNT(*) FROM sources s WHERE s.release_id = r.id) AS n_sources"
                " FROM releases r WHERE r.post_id = ? ORDER BY r.id", (row["id"],)).fetchall()
        return dict(row), releases

    def test_unknown_type_is_stored_as_null_not_a_string(self):
        """
        'unknown' must be absent, not a value.

        merge_catalogs currently maps any non-'movie' staging value onto 'series',
        so the literal string 'unknown' would itself become a false series.
        """
        fixture = next(f for f in PATHOLOGICAL if f["slug"] == "after-we-collided-2020-hindi-1xbet")
        identity = self.save(fixture)
        self.assertIsNone(identity["media_type"])
        row, _ = self.read(identity["canonical_key"])
        self.assertIsNone(row["media_type"])

    def test_derived_fields_land_in_the_staging_row(self):
        identity = self.save(FREE_NIGHTS, imdb_id=FREE_NIGHTS_IMDB)
        row, releases = self.read(identity["canonical_key"])
        self.assertEqual(row["title"], "Five Nights at Freddy's 2")
        self.assertEqual(row["year"], 2025)
        self.assertEqual(row["media_type"], "movie")
        self.assertEqual(row["canonical_key"], "five-nights-at-freddys-2_2025")
        self.assertEqual(row["imdb_id"], FREE_NIGHTS_IMDB)
        self.assertEqual(len(releases), 1)
        self.assertEqual(releases[0]["n_sources"], 1)

    def test_every_scraped_release_and_source_survives_the_save(self):
        fixture = next(f for f in PATHOLOGICAL if f["slug"] == "mobland-s1-hindi")
        extra = [
            release_for("S01 E01", "1080p", 1_200_000_000, "ep1", season=1, episode=1),
            release_for("S01 E02", "1080p", 1_300_000_000, "ep2", season=1, episode=2),
        ]
        identity = self.save(fixture, extra_releases=extra)
        _, releases = self.read(identity["canonical_key"])
        self.assertEqual(len(releases), 3, "zero data loss: no scraped row may be dropped")
        self.assertEqual([r["episode_number"] for r in releases], [None, 1, 2])
        self.assertEqual(sum(r["n_sources"] for r in releases), 3)

    def test_two_pages_of_one_season_upsert_onto_one_staging_row(self):
        """Same derived key twice must not fork a second work in staging."""
        fixture = dict(FREE_NIGHTS)
        first = self.save(fixture)
        fixture["raw"] = ("Five Nights at Freddy's 2 (2025) Hindi Dubbed (DD 5.1) &amp; English "
                          "[Dual Audio] WEB-DL 1080p 720p 480p HD [Full Movie] 1XBET")
        second = self.save(fixture)
        self.assertEqual(first["canonical_key"], second["canonical_key"])
        with sqlite3.connect(str(self.db_path)) as conn:
            count = conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
        self.assertEqual(count, 1)


class LedgerConflictTests(unittest.TestCase):
    """
    End-to-end proof: the same page that produced a 'different media type'
    conflict now merges into the existing record, and the v2 projection files it
    under one movie work.
    """

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.tmp = Path(self.temp_dir.name)
        self._saved_db_path = fast_fetch.DB_PATH
        self.addCleanup(setattr, fast_fetch, "DB_PATH", self._saved_db_path)

        self.target = self.tmp / "unified.db"
        fast_fetch.DB_PATH = self.target
        fast_fetch.init_db()
        # Another site ingested the film first, correctly, as a movie.
        fast_fetch.save_scraped_data(
            {
                "url": "https://other.example/five-nights-at-freddys-2-2025",
                "slug": "five-nights-at-freddys-2-2025",
                "title": "Five Nights at Freddy's 2 (2025)",
                "clean_title": "Five Nights at Freddy's 2",
                "year": 2025,
                "content_type": "movie",
                "imdb_id": FREE_NIGHTS_IMDB,
                "source_site": "otherhd",
                "releases": [release_for("Other HD 1080p", "1080p", 2_400_000_000, "other1")],
            },
            enrich_metadata=False,
            ensure_db=False,
        )

    def make_staging_db(self, name, media_type, canonical_key, title):
        db_path = self.tmp / name
        import_katmoviehd.init_staging_db(db_path)
        self.assertTrue(import_katmoviehd.save_post_to_staging_db(db_path, {
            "canonical_key": canonical_key,
            "title": title,
            "original_title": FREE_NIGHTS["raw"],
            "year": 2025,
            "media_type": media_type,
            "imdb_id": FREE_NIGHTS_IMDB,
            "poster_url": None,
            "synopsis": "A synopsis that mentions an episode by name.",
            "genres": json.dumps(FREE_NIGHTS["categories"]),
            "rating": None,
            "site": "katmoviehd",
            "post_url": f"https://new.katmoviehd.top/{FREE_NIGHTS['slug']}",
            "releases": [release_for("720p Links [821MB]", "720p", 861150158, "kat1")],
        }))
        return db_path

    def ledger(self):
        with sqlite3.connect(str(self.target)) as conn:
            conn.row_factory = sqlite3.Row
            posts = [dict(r) for r in conn.execute(
                "SELECT id, url, clean_title, year, content_type, canonical_key, imdb_id"
                " FROM posts ORDER BY id")]
            has_conflicts = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='merge_conflicts'"
            ).fetchone()
            conflicts = ([dict(r) for r in conn.execute("SELECT * FROM merge_conflicts")]
                         if has_conflicts else [])
        return posts, conflicts

    def test_the_old_staging_row_reproduces_the_conflict(self):
        staging = self.make_staging_db(
            "legacy.db", LEGACY_FIVE_NIGHTS["media_type"],
            LEGACY_FIVE_NIGHTS["canonical_key"], LEGACY_FIVE_NIGHTS["title"])
        stats = merge_catalogs.merge_site_db(staging, self.target, verbose=False)
        _, conflicts = self.ledger()
        self.assertEqual(stats["posts_conflicted"], 1)
        self.assertEqual(len(conflicts), 1)
        self.assertIn("different media type", conflicts[0]["error"])

    def test_the_fixed_staging_row_merges_without_conflict(self):
        identity = derive(FREE_NIGHTS)
        staging = self.make_staging_db(
            "fixed.db", identity["media_type"], identity["canonical_key"], identity["title"])
        stats = merge_catalogs.merge_site_db(staging, self.target, verbose=False)
        _, conflicts = self.ledger()
        self.assertEqual(conflicts, [], "identity conflict survived the fix")
        self.assertEqual(stats["posts_conflicted"], 0)
        self.assertEqual(stats["posts_merged"], 1)

        posts, _ = self.ledger()
        self.assertEqual(len(posts), 1, "the film must not fork a second catalog record")
        self.assertEqual(posts[0]["content_type"], "movie")
        self.assertEqual(posts[0]["imdb_id"], FREE_NIGHTS_IMDB)
        # Zero data loss: the displaced page keeps its own release and source rows.
        with sqlite3.connect(str(self.target)) as conn:
            releases = conn.execute("SELECT COUNT(*) FROM releases").fetchone()[0]
            sources = conn.execute("SELECT COUNT(*) FROM download_sources").fetchone()[0]
            pages = conn.execute(
                "SELECT COUNT(DISTINCT url) FROM post_sources WHERE source_site = 'katmoviehd'"
            ).fetchone()[0]
        self.assertEqual(releases, 2)
        self.assertEqual(sources, 2)
        self.assertGreaterEqual(pages, 1)

    def test_projection_files_the_merged_record_as_one_movie_work(self):
        identity = derive(FREE_NIGHTS)
        staging = self.make_staging_db(
            "fixed.db", identity["media_type"], identity["canonical_key"], identity["title"])
        merge_catalogs.merge_site_db(staging, self.target, verbose=False)

        with sqlite3.connect(str(self.target)) as conn:
            conn.row_factory = sqlite3.Row
            catalog_v2.project(conn, verbose=False)
            works = [dict(r) for r in conn.execute(
                "SELECT work_key, title, year, work_type, imdb_id, site_count, release_count"
                " FROM cat_works ORDER BY id")]
            links = [dict(r) for r in conn.execute(
                "SELECT source_site, kind, url FROM cat_links ORDER BY id")]
            seasons = conn.execute(
                "SELECT COUNT(*) FROM cat_seasons WHERE number > 0").fetchone()[0]

        self.assertEqual(len(works), 1, works)
        self.assertEqual(works[0]["work_type"], "movie")
        self.assertEqual(works[0]["work_key"], f"imdb:{FREE_NIGHTS_IMDB}")
        self.assertEqual(works[0]["year"], 2025)
        self.assertEqual(works[0]["site_count"], 2)
        self.assertEqual(len(links), 2)
        self.assertEqual({l["source_site"] for l in links}, {"katmoviehd", "otherhd"})
        self.assertEqual(seasons, 0, "a movie must not project any numbered season")

    def test_a_real_season_still_projects_as_a_series(self):
        """The fix must not flatten genuine seasons into movies."""
        fixture = next(f for f in PATHOLOGICAL if f["slug"] == "mobland-s1-hindi")
        identity = derive(fixture)
        db_path = self.tmp / "season.db"
        import_katmoviehd.init_staging_db(db_path)
        import_katmoviehd.save_post_to_staging_db(db_path, {
            "canonical_key": identity["canonical_key"],
            "title": identity["title"],
            "original_title": fixture["raw"],
            "year": identity["year"],
            "media_type": identity["media_type"],
            "imdb_id": "tt29863334",
            "poster_url": None,
            "synopsis": None,
            "genres": json.dumps(fixture["categories"]),
            "rating": None,
            "site": "katmoviehd",
            "post_url": f"https://new.katmoviehd.top/{fixture['slug']}",
            "releases": [
                release_for("S01 E01", "1080p", 1_200_000_000, "s1e1", season=1, episode=1),
                release_for("S01 E02", "1080p", 1_300_000_000, "s1e2", season=1, episode=2),
            ],
        })
        stats = merge_catalogs.merge_site_db(db_path, self.target, verbose=False)
        _, conflicts = self.ledger()
        self.assertEqual(conflicts, [])
        self.assertEqual(stats["posts_merged"], 1)

        posts, _ = self.ledger()
        kat = [p for p in posts if p["canonical_key"] == "mobland_s1"]
        self.assertEqual(len(kat), 1)
        self.assertEqual(kat[0]["content_type"], "series")
        with sqlite3.connect(str(self.target)) as conn:
            conn.row_factory = sqlite3.Row
            catalog_v2.project(conn, verbose=False)
            work = conn.execute(
                "SELECT id, work_type, title FROM cat_works WHERE imdb_id = 'tt29863334'"
            ).fetchone()
            episodes = conn.execute(
                "SELECT COUNT(*) FROM cat_episodes WHERE work_id = ?", (work["id"],)
            ).fetchone()[0]
        self.assertEqual(work["work_type"], "series")
        self.assertEqual(work["title"], "MobLand")
        self.assertEqual(episodes, 2)


class ExtractorWiringTests(unittest.TestCase):
    """
    `extract_post_data_katmoviehd()` must feed the ladder with the page's own
    evidence rather than with prose scraped from the synopsis.
    """

    def test_page_field_and_category_path_drive_the_type(self):
        page_field = import_katmoviehd._page_field_type
        self.assertEqual(page_field("<td>Movie Name:</td>"), "movie")
        self.assertEqual(page_field("<td>Series Name:</td>"), "series")
        self.assertEqual(page_field("<td>TV Series Name:</td>"), "series")
        self.assertEqual(page_field("<p>Movie Name:</p><p>Series Name:</p>"), "conflict")
        self.assertIsNone(page_field("no structured label at all"))

    def test_episode_word_in_prose_is_not_type_evidence(self):
        """The old parser typed a film as a series on this; the fix never sees the prose."""
        identity = import_katmoviehd.derive_katmoviehd_identity(
            "The Bus: A French Football Mutiny (2026) Full Movie", categories=["dubbed-movie"])
        self.assertEqual(identity["media_type"], "movie")

    def test_default_season_hint_uses_the_derived_season(self):
        releases = import_katmoviehd.parse_katmoviehd_releases(
            '<a href="https://kmhd.example/s02e03">Episode 03 [1080p]</a>', default_season=2)
        self.assertTrue(any(r["episode_number"] == 3 and r["season_number"] == 2
                            for r in releases), releases)

    def test_module_exposes_the_identity_ladder_entry_point(self):
        self.assertTrue(callable(import_katmoviehd.derive_katmoviehd_identity))
        identity = import_katmoviehd.derive_katmoviehd_identity("Colony (2026) Full Movie")
        self.assertEqual(set(identity), {
            "title", "original_title", "year", "season", "media_type",
            "canonical_key", "evidence"})


if __name__ == "__main__":
    unittest.main()
