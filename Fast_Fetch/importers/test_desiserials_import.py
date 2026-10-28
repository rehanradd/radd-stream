#!/usr/bin/env python3
"""
test_desiserials_import.py — offline unit tests for the DesiSerials importer.

Nothing here reaches the network. `socket.socket` is replaced with a raiser for
the whole module, so an accidental live request fails the run instead of passing
it. The fixtures are shaped from what the site published on 2026-10-28: a REST
record whose category IS the series and whose author IS the network, and a
rendered page holding exactly one player iframe.

The two rules this suite exists to keep:

1. An iframe of a host this project cannot open is catalog evidence, not a
   playable row. Every source is `playback_type='iframe'` and nothing in the
   record may carry a byte URL, a token, or a Referer.
2. Several thousand episodes write ONE series row, so the adult flag has to be
   sticky and the release write has to be additive. A wholesale replace would
   leave each series holding only the last episode crawled, and a COALESCE over
   `is_18_plus` would let any clean episode un-flag a series already graded.
"""

from __future__ import annotations

import json
import shutil
import socket
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import import_desiserials as ds  # noqa: E402


class _NoLiveSocket:
    def __init__(self, *a, **kw):
        raise AssertionError("an offline test tried to open a socket")


socket.socket = _NoLiveSocket  # type: ignore[assignment]


VK_URL = "//vkspeed.com/embed-8i6f58m6to0g.html"
VK_ABS = "https://vkspeed.com/embed-8i6f58m6to0g.html"
UPBOLT_URL = "https://upbolt.to/emb-y1q5jqsfgotr"

EPISODE_PAGE = (
    "<html><head>"
    '<meta property="og:image" content="https://desiserials.watch/wp-content/'
    'uploads/2026/08/Untitled-design-32.jpg">'
    '<script async src="https://www.googletagmanager.com/gtag/js?id=G-NWW2G3SEPY">'
    "</script></head><body>"
    '<div class="entry-content">'
    f'<iframe src="{VK_URL}" height="380" width="100%" frameborder="0" '
    'scrolling="no" allowfullscreen></iframe>'
    '<iframe src="https://ct.jumbaouttold.com/sJWTVsg4dZy/116951" width="300" '
    'height="50"></iframe>'
    "</div><footer>"
    f'<iframe src="https://exoclick.com/zon/8812" width="1" height="1"></iframe>'
    "</footer></body></html>"
)

CONTENT = (
    "<p>Watch Online <strong>Pushpa Impossible 28th October 2026</strong> Full "
    "Episode 1371 Video in HD By <a href=\"/author/sonyliv\"><strong>Sonyliv"
    "</strong></a>. Hindi Desi Serial Pushpa Impossible Today Latest Episode In "
    "High Quality. Sony Tv Drama Pushpa Impossible 28 October 2026 Complete Show "
    "Video.<br /> <strong>Serial Name:</strong> Pushpa Impossible<br /> "
    "<strong>Media Owner:</strong> Sony Tv and Sonyliv<br /> "
    "<strong>Media By:</strong> VKspeed/VKprime</p>"
)


def wp_post(**over) -> dict:
    record = {
        "id": 61025,
        "slug": "pushpa-impossible-28th-october-2026-full-episode-1371-watch-online",
        "link": "https://desiserials.watch/"
                "pushpa-impossible-28th-october-2026-full-episode-1371-watch-online/",
        "title": {"rendered": "Pushpa Impossible 28th October 2026 "
                              "Full Episode 1371 Watch Online"},
        "date": "2026-10-28T08:02:11",
        "modified": "2026-10-28T08:02:11",
        "excerpt": {"rendered": "<p>Watch Online Pushpa Impossible</p>"},
        "content": {"rendered": CONTENT},
        "_embedded": {
            "wp:term": [
                [{"id": 4412, "name": "Pushpa Impossible", "slug": "pushpa-impossible",
                  "taxonomy": "category",
                  "yoast_head": "<!-- 2 KB of SEO noise the queue must not carry -->"}],
                [],
            ],
            "author": [{"name": "Sonyliv", "_links": {"self": [{"href": "x"}]}}],
            "wp:featuredmedia": [{"source_url": "https://desiserials.watch/wp-content/"
                                                 "uploads/2026/06/Untitled-design-28.jpg"}],
        },
    }
    record.update(over)
    return record


def _flag(db_path, key: str, column: str = "is_18_plus"):
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(f"SELECT {column} FROM posts WHERE canonical_key = ?",
                           (key,)).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# The published strings
# ---------------------------------------------------------------------------

class TestTitleGrammar(unittest.TestCase):
    def test_series_date_and_episode_number_come_out_of_the_title(self):
        parsed = ds.parse_episode_title(
            "Kaun Banega Crorepati 18 28th October 2026 Full Episode 58 Watch Online")
        self.assertEqual(parsed["series_label"], "Kaun Banega Crorepati 18")
        self.assertEqual(parsed["episode"], 58)
        self.assertEqual(parsed["air_date"], "2026-10-28")
        self.assertIsNone(parsed["season"])

    def test_a_show_name_ending_in_a_number_keeps_it_in_the_label(self):
        """'Bigg Boss 20' is the name as published, not season 20 asserted."""
        parsed = ds.parse_episode_title("Bigg Boss 20 28th October 2026 Full Episode 58")
        self.assertEqual(parsed["series_label"], "Bigg Boss 20")
        self.assertIsNone(parsed["season"])

    def test_an_explicit_season_in_the_title_is_taken(self):
        parsed = ds.parse_episode_title("Fursat E Dil 5th November 2025 Season 2 Episode 25")
        self.assertEqual((parsed["season"], parsed["episode"]), (2, 25))

    def test_ordinal_and_plain_day_forms_both_parse(self):
        self.assertEqual(ds.parse_episode_title(
            "X 1st January 2026 Full Episode 2")["air_date"], "2026-01-01")
        self.assertEqual(ds.parse_episode_title(
            "X 21 October 2026 Full Episode 2")["air_date"], "2026-10-21")

    def test_a_title_with_no_date_keeps_the_label_up_to_the_episode(self):
        parsed = ds.parse_episode_title("Mannat Full Episode 12 Watch Online")
        self.assertEqual(parsed["series_label"], "Mannat")
        self.assertEqual(parsed["episode"], 12)
        self.assertIsNone(parsed["air_date"])

    def test_a_movie_post_is_marked_as_one(self):
        self.assertTrue(ds.parse_episode_title("Dhaakad 2026 Full Movie")["is_movie"])

    def test_no_episode_number_is_none_not_zero(self):
        self.assertIsNone(ds.parse_episode_title("Some Special Episode")["episode"])


class TestContentFields(unittest.TestCase):
    def test_the_three_labeled_fields_are_read(self):
        fields = ds.parse_content_fields(CONTENT)
        self.assertEqual(fields["serial_name"], "Pushpa Impossible")
        self.assertEqual(fields["media_owner"], "Sony Tv and Sonyliv")
        self.assertEqual(fields["media_by"], "VKspeed/VKprime")

    def test_the_blurb_stops_where_the_labeled_block_starts(self):
        blurb = ds.parse_content_fields(CONTENT)["blurb"]
        self.assertIn("Watch Online", blurb)
        self.assertNotIn("Serial Name:", blurb)

    def test_a_post_with_no_labeled_block_yields_empty_strings(self):
        self.assertEqual(ds.parse_content_fields("<p>Nothing here</p>")["serial_name"], "")


# ---------------------------------------------------------------------------
# The player: what may become a source row
# ---------------------------------------------------------------------------

class TestPlayers(unittest.TestCase):
    def test_the_player_iframe_is_found_and_made_absolute(self):
        players = ds.players_from_page(EPISODE_PAGE)
        self.assertEqual([p["url"] for p in players], [VK_ABS])
        self.assertEqual(players[0]["service"], "vkspeed")
        self.assertEqual(players[0]["resource_id"], "embed-8i6f58m6to0g")

    def test_an_ad_frame_is_not_a_source(self):
        """The page ships tag-manager and ad-network frames; only the player counts."""
        blob = json.dumps(ds.players_from_page(EPISODE_PAGE))
        for forbidden in ("googletagmanager", "jumbaouttold", "exoclick"):
            self.assertNotIn(forbidden, blob)

    def test_a_player_hosted_frame_with_an_unexpected_path_is_dropped(self):
        page = '<iframe src="https://vkspeed.com/redirect?a=1"></iframe>'
        self.assertEqual(ds.players_from_page(page), [])

    def test_the_site_hosting_its_own_iframe_is_not_a_source(self):
        page = ('<iframe src="https://desiserials.watch/preview/x"></iframe>')
        self.assertEqual(ds.players_from_page(page), [])

    def test_duplicate_frames_of_one_embed_become_one_row(self):
        page = f'<iframe src="{VK_ABS}"></iframe><iframe src="//vkspeed.com/' \
               f'embed-8i6f58m6to0g.html"></iframe>'
        self.assertEqual(len(ds.players_from_page(page)), 1)

    def test_two_different_players_on_one_episode_both_survive(self):
        page = f'<iframe src="{VK_ABS}"></iframe><iframe src="{UPBOLT_URL}"></iframe>'
        players = ds.players_from_page(page)
        self.assertEqual([p["service"] for p in players], ["vkspeed", "upbolt"])

    def test_a_frame_that_is_not_a_real_url_is_skipped(self):
        self.assertEqual(ds.players_from_page('<iframe src="javascript:void(0)">'
                                              '</iframe>'), [])
        self.assertEqual(ds.players_from_page("<iframe></iframe>"), [])

    def test_resource_id_prefers_the_embed_segment_over_a_tracking_suffix(self):
        self.assertEqual(ds.embed_resource_id(
            "https://upbolt.to/emb-y1q5jqsfgotr?utm=ad"), "emb-y1q5jqsfgotr")

    def test_normalize_url_rejects_a_non_http_scheme(self):
        self.assertEqual(ds.normalize_url("data:text/html,<script>"), "")


# ---------------------------------------------------------------------------
# Classification: only what the site itself claims
# ---------------------------------------------------------------------------

class TestClassification(unittest.TestCase):
    def test_the_network_the_site_credits_drives_country(self):
        """Whichever credited name matches first, the country is the published one."""
        network, (country, industry) = ds.network_from("Hum TV and URDU1")
        self.assertIn(network, ("Hum TV", "URDU1"))
        self.assertEqual((country, industry), ("Pakistan", "television"))
        self.assertEqual(ds.network_from("Zee5")[1][0], "India")

    def test_an_unrecognized_network_claims_no_country(self):
        self.assertEqual(ds.network_from("Some Blog"), (None, (None, None)))

    def test_languages_come_only_from_words_the_site_wrote(self):
        self.assertEqual(ds.languages_from_text("Hindi Desi Serial", ""), ["Hindi"])
        self.assertEqual(ds.languages_from_text("Hindi Urdu Punjabi"),
                         ["Hindi", "Urdu", "Punjabi"])
        self.assertEqual(ds.languages_from_text("no names here"), [])

    def test_adult_is_flagged_only_on_explicit_tokens(self):
        self.assertEqual(ds.looks_adult("Some Serial 18+ Cut"), 1)
        self.assertEqual(ds.looks_adult("Pushpa Impossible"), 0)

    def test_brand_and_seo_suffix_are_scrubbed(self):
        self.assertEqual(ds.scrub_brand("[DesiSerials] Mannat Watch Online"), "Mannat")


# ---------------------------------------------------------------------------
# The record, and the rule it exists to keep
# ---------------------------------------------------------------------------

class TestRecord(unittest.TestCase):
    def setUp(self):
        self.record = ds.build_record(wp_post(), EPISODE_PAGE, wp_post()["link"])

    def test_one_episode_builds_one_release_under_the_series_category_row(self):
        self.assertIsNotNone(self.record)
        self.assertEqual(self.record["canonical_key"], "pushpa-impossible")
        self.assertEqual(self.record["clean_title"], "Pushpa Impossible")
        self.assertEqual(len(self.record["releases"]), 1)
        release = self.record["releases"][0]
        self.assertEqual(release["episode_number"], 1371)
        self.assertEqual(release["label"], "E1371")
        self.assertEqual(release["origin_url"], wp_post()["link"])
        self.assertEqual(release["air_date"], "2026-10-28")

    def test_the_player_is_stored_as_an_iframe_row_and_nothing_more(self):
        source = self.record["releases"][0]["sources"][0]
        self.assertEqual(source["playback_type"], "iframe")
        self.assertEqual(source["status"], "unverified")
        self.assertEqual(source["is_temporary"], 0)
        self.assertIsNone(source["final_url"])
        self.assertEqual(source["source_url"], VK_ABS)

    def test_no_resolved_byte_url_token_or_referer_appears_anywhere(self):
        blob = json.dumps(self.record)
        for forbidden in (".m3u8", ".mp4", "token=", "Referer", "file=",
                          "googletagmanager", "exoclick"):
            self.assertNotIn(forbidden, blob, f"leaked: {forbidden}")

    def test_the_poster_comes_from_featured_media_not_the_page(self):
        self.assertTrue(self.record["poster_url"].endswith("Untitled-design-28.jpg"))
        self.assertIn("wp:featuredmedia", self.record["raw_meta"]["poster_source"])

    def test_a_page_with_no_og_image_falls_back_to_none_gracefully(self):
        record = ds.build_record(wp_post(_embedded={"wp:term": [
            [{"name": "X", "slug": "x", "taxonomy": "category"}], []]}),
            '<iframe src="https://vkspeed.com/embed-aaaaaaa1111.html"></iframe>',
            "https://desiserials.watch/x-1/")
        self.assertIsNone(record["poster_url"])

    def test_an_episode_with_no_series_term_is_not_invented_a_parent(self):
        post = wp_post(_embedded={"wp:term": [[], []]})
        post["title"] = {"rendered": "Full Episode 3 Watch Online"}
        self.assertEqual(ds.build_record(post, "", post["link"]), None)

    def test_a_page_with_no_player_produces_no_record(self):
        self.assertIsNone(ds.build_record(wp_post(), "<p>no player</p>",
                                          wp_post()["link"]))

    def test_no_category_slug_keys_the_series_from_its_label(self):
        post = wp_post(_embedded={"wp:term": [
            [{"name": "Tu Juliet Jatt Di", "slug": "", "taxonomy": "category"}], []]})
        record = ds.build_record(post, EPISODE_PAGE, post["link"])
        self.assertEqual(record["canonical_key"], "tu-juliet-jatt-di")
        self.assertNotIn("28th-october", record["canonical_key"])

    def test_the_season_is_read_from_the_prose_and_its_source_is_recorded(self):
        """The site writes the season in a sentence, not in a field."""
        content = CONTENT.replace("Hindi Desi Serial Pushpa Impossible Today",
                                  "Hindi Desi Serial Kaun Banega Crorepati Season 18 Today")
        post = wp_post(title={"rendered": "Kaun Banega Crorepati 18 28th October 2026 "
                                          "Full Episode 58 Watch Online"},
                       content={"rendered": content})
        record = ds.build_record(post, EPISODE_PAGE, post["link"])
        release = record["releases"][0]
        self.assertEqual(release["season_number"], 18)
        self.assertEqual(release["label"], "S18E058")
        self.assertEqual(record["raw_meta"]["season_source"], "content 'Season N'")

    def test_a_season_is_not_invented_from_a_number_in_the_show_name(self):
        record = ds.build_record(
            wp_post(title={"rendered": "Bigg Boss 20 28th October 2026 "
                                      "Full Episode 58 Watch Online"}),
            EPISODE_PAGE, wp_post()["link"])
        self.assertIsNone(record["releases"][0]["season_number"])
        self.assertEqual(record["raw_meta"]["season_source"], "not published")

    def test_nothing_is_claimed_as_a_year_the_site_never_published(self):
        self.assertIsNone(self.record["year"])
        self.assertEqual(self.record["raw_meta"]["year_source"],
                         "not published at series level")

    def test_an_empty_tag_group_is_not_mistaken_for_genres(self):
        self.assertIsNone(self.record["genres"])
        self.assertEqual(self.record["raw_meta"]["networks_published"], ["Sonyliv"])


# ---------------------------------------------------------------------------
# The queue projection: the shape that broke AnimaHD's sync
# ---------------------------------------------------------------------------

class TestQueuePayload(unittest.TestCase):
    def test_the_live_grouped_wp_term_survives_the_projection(self):
        payload = ds._queue_json(wp_post())
        groups = payload["_embedded"]["wp:term"]
        self.assertEqual([[t["name"] for t in g] for g in groups],
                         [["Pushpa Impossible"], []])
        self.assertEqual(ds.terms_from_embed(payload), ds.terms_from_embed(wp_post()))

    def test_the_boilerplate_and_seo_noise_stay_out_of_the_queue(self):
        payload = ds._queue_json(wp_post())
        blob = json.dumps(payload)
        self.assertNotIn("yoast_head", blob)
        self.assertNotIn("_links", blob)
        self.assertIn("Serial Name", payload["content"]["rendered"])
        self.assertLess(len(blob), 3000)

    def test_a_post_with_no_embedded_block_projects_empty_groups(self):
        payload = ds._queue_json({"id": 1, "link": "https://desiserials.watch/x/"})
        self.assertEqual(payload["_embedded"]["wp:term"], [])
        self.assertEqual(ds.terms_from_embed(payload)["series_name"], "")

    def test_a_term_that_is_not_a_dict_is_skipped_not_walked_into(self):
        post = wp_post(_embedded={"wp:term": [["not-a-dict"], None]})
        payload = ds._queue_json(post)
        self.assertEqual(payload["_embedded"]["wp:term"], [[], []])


# ---------------------------------------------------------------------------
# Staging writes: many episodes, one series row
# ---------------------------------------------------------------------------

class TestStagingWrites(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="desiserials_")
        self.db = Path(self.dir) / "desiserials.db"

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _episode(self, number: int, series: str = "Pushpa Impossible",
                 slug: str = "pushpa-impossible", **over) -> dict:
        title = f"{series} 28th October 2026 Full Episode {number} Watch Online"
        link = f"https://desiserials.watch/{slug}-episode-{number}/"
        post = wp_post(title={"rendered": title}, link=link,
                       slug=f"{slug}-episode-{number}",
                       _embedded={"wp:term": [
                           [{"name": series, "slug": slug, "taxonomy": "category"}],
                           []],
                           "author": [{"name": "Sonyliv"}],
                           "wp:featuredmedia": []}, **over)
        embed = f"https://vkspeed.com/embed-z{id(post):012d}.html"
        return ds.build_record(post, f'<iframe src="{embed}"></iframe>', link)

    def _counts(self):
        conn = sqlite3.connect(self.db)
        try:
            return (conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0],
                    conn.execute("SELECT COUNT(*) FROM releases").fetchone()[0],
                    conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0])
        finally:
            conn.close()

    def test_two_episodes_of_one_series_make_one_post_and_two_releases(self):
        """The trap this site sets: replacing wholesale would leave one episode."""
        ds.export_staging(self.db, [self._episode(1), self._episode(2)])
        self.assertEqual(self._counts(), (1, 2, 2))

    def test_recrawling_one_episode_updates_it_without_touching_its_siblings(self):
        first, second = self._episode(1), self._episode(2)
        ds.export_staging(self.db, [first, second])
        moved = self._episode(1)
        moved["releases"][0]["bridge_url"] = "https://upbolt.to/emb-changed0001"
        ds.export_staging(self.db, [moved])
        self.assertEqual(self._counts(), (1, 2, 2))
        conn = sqlite3.connect(self.db)
        try:
            bridges = [r[0] for r in conn.execute(
                "SELECT bridge_url FROM releases ORDER BY episode_number")]
        finally:
            conn.close()
        self.assertTrue(bridges[0].endswith("emb-changed0001"), bridges)
        self.assertTrue(bridges[1].startswith("https://vkspeed.com/"), bridges)

    def test_the_adult_flag_survives_a_later_clean_episode_of_the_same_series(self):
        """3,646 episodes write one row: one 0 must not un-flag what was graded 1."""
        graded = self._episode(1)
        graded["is_18_plus"] = 1
        ds.export_staging(self.db, [graded])
        self.assertEqual(_flag(self.db, graded["canonical_key"]), 1)
        ds.export_staging(self.db, [self._episode(2)])
        self.assertEqual(_flag(self.db, graded["canonical_key"]), 1,
                         "a clean episode cleared an adult flag already set")

    def test_a_series_first_seen_clean_still_becomes_adult_later(self):
        ds.export_staging(self.db, [self._episode(1)])
        self.assertEqual(_flag(self.db, "pushpa-impossible"), 0)
        upgraded = self._episode(2)
        upgraded["is_18_plus"] = 1
        ds.export_staging(self.db, [upgraded])
        self.assertEqual(_flag(self.db, "pushpa-impossible"), 1)

    def test_an_episode_keeps_its_own_air_date_and_detail(self):
        ds.export_staging(self.db, [self._episode(7)])
        conn = sqlite3.connect(self.db)
        try:
            row = conn.execute("SELECT air_date, raw_meta FROM releases").fetchone()
        finally:
            conn.close()
        self.assertEqual(row[0], "2026-10-28")
        self.assertEqual(json.loads(row[1])["episode_claim"], 7)

    def test_a_source_row_that_claims_an_unknown_status_is_stored_unverified(self):
        record = self._episode(3)
        record["releases"][0]["sources"][0]["status"] = "kind-of-working"
        ds.export_staging(self.db, [record])
        conn = sqlite3.connect(self.db)
        try:
            stored = conn.execute("SELECT status FROM sources").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(stored, "unverified")

    def test_a_record_without_a_title_or_key_is_skipped_not_written(self):
        totals = ds.export_staging(self.db, [{"clean_title": "", "canonical_key": ""}])
        self.assertEqual(totals["skipped"], 1)
        self.assertEqual(self._counts(), (0, 0, 0))


# ---------------------------------------------------------------------------
# Isolation: which file this module is allowed to open
# ---------------------------------------------------------------------------

class TestStagingIsolation(unittest.TestCase):
    def test_the_default_database_is_the_staging_file_not_production(self):
        self.assertEqual(str(ds.DEFAULT_DB_PATH),
                         "/home/ubuntu/radd-stream-data/desiserials.db")
        self.assertNotIn("fast_fetch", str(ds.DEFAULT_DB_PATH))

    def test_the_default_source_status_is_unverified(self):
        self.assertEqual(ds.DEFAULT_SOURCE_STATUS, "unverified")

    def test_only_measured_player_hosts_may_name_a_source_url(self):
        for url in (VK_ABS, UPBOLT_URL):
            self.assertTrue(ds._allowed_source_url(url), url)
        self.assertFalse(ds._allowed_source_url("https://exoclick.com/zon/1"))
        self.assertFalse(ds._allowed_source_url(""))

    def test_the_slug_used_for_a_rest_lookup_is_the_published_segment(self):
        """`?slug=` is a key, not a title: trimming the suffix makes the post missing."""
        self.assertEqual(
            ds.slug_from("https://desiserials.watch/pushpa-impossible-28th-october-"
                         "2026-full-episode-1371-watch-online/"),
            "pushpa-impossible-28th-october-2026-full-episode-1371-watch-online")

    def test_the_catalog_is_read_from_the_public_rest_collection(self):
        self.assertTrue(ds.REST_POSTS.startswith(ds.BASE_URL))
        self.assertIn("wp-json/wp/v2/posts", ds.REST_POSTS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
