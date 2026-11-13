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


class BandServicePriorityTests(unittest.TestCase):
    """Phase C item 4: the §5 measured per-band priority (grand-scale probe,
    14,089 links, 2026-11-13). The bonus orders copies of the SAME kind by
    measured alive rate; it never closes the kind gap, and an unlisted
    service is still a candidate — just not a measured one."""

    def test_priority_band_key_keeps_the_measured_distinctions(self):
        for text, key in (
                ("1080p HEVC", "hevc"), ("720p HEVC", "hevc"),
                ("1080p", "1080p"), ("720p", "720p"), ("480p", "480p"),
                ("360p", "360p"), ("240p", "240p"), ("4K", "2160p"),
                ("auto", "auto"), ("HD", "hd"), ("HDTV", "hd"),
                ("WEB-DL", "unspecified"), ("Download", "unspecified")):
            self.assertEqual(tiers.priority_band_key(text), key, text)

    def test_band_service_bonus_orders_the_720p_serve_list(self):
        # §5 720p serve: 5centscdn, mp4moviez, fsl_r2; backups: hubcloud, vidbolt.
        ordered = ("5centscdn", "mp4moviez", "fsl_r2", "hubcloud", "vidbolt")
        scores = [tiers.score(link(service=s, playback_type="direct",
                                   status="active"), "720p", "720p")
                  for s in ordered]
        self.assertEqual(scores, sorted(scores, reverse=True), ordered)
        self.assertGreater(scores[0], scores[-1])

    def test_the_bonus_never_closes_the_kind_gap(self):
        # A url copy on the best 720p host still trails a direct copy on
        # the third host: the measured order decides within a kind, never
        # across one.
        page = link(service="mp4moviez", playback_type="url", status="active")
        direct = link(service="fsl_r2", playback_type="direct", status="active")
        self.assertGreater(tiers.score(direct, "720p", "720p"),
                           tiers.score(page, "720p", "720p"))

    def test_an_unlisted_service_is_still_a_candidate(self):
        # mobilejsr is 410/514 dead — never served first — but it is not
        # excluded by the table: it earns 0 and keeps its kind/status score.
        dead_host = link(service="mobilejsr", playback_type="direct",
                         status="active")
        self.assertEqual(tiers.band_service_bonus("mobilejsr", "720p"), 0)
        self.assertGreater(tiers.score(dead_host, "720p", "720p"), 0)

    def test_for_release_picks_the_measured_winner_and_two_backups(self):
        ladder = tiers.for_release({"quality": "720p"}, [
            link(id=1, service="hubcloud"),
            link(id=2, service="mobilejsr"),
            link(id=3, service="fsl_r2"),
            link(id=4, service="mp4moviez"),
            link(id=5, service="5centscdn")])
        tier = ladder["tiers"][0]
        self.assertEqual(tier["link"]["service"], "5centscdn")
        self.assertEqual([item["service"] for item in tier["backups"]],
                         ["mp4moviez", "fsl_r2"])
        self.assertEqual(len(tier["backups"]), tiers.BACKUP_LIMIT)

    def test_the_auto_band_serves_aryzap_vod(self):
        ladder = tiers.for_release({"quality": "auto"}, [
            link(id=1, service="dramadog"),
            link(id=2, service="aryzap-vod")])
        self.assertEqual(ladder["tiers"][0]["link"]["service"], "aryzap-vod")

    def test_the_1080p_serve_is_fsl_r2_then_vidbolt(self):
        self.assertGreater(
            tiers.score(link(service="fsl_r2"), "1080p", "1080p"),
            tiers.score(link(service="vidbolt"), "1080p", "1080p"))
        self.assertGreater(
            tiers.score(link(service="vidbolt"), "1080p", "1080p"),
            tiers.score(link(service="hubcloud"), "1080p", "1080p"))

    def test_candidate_order_sql_puts_the_band_first(self):
        sql = tiers.candidate_order_sql(band="720p")
        self.assertLess(sql.index("5centscdn"), sql.index("fsl_r2"))
        self.assertLess(sql.index("fsl_r2"), sql.index("hubcloud_10g"))
        # Without a band the SQL is byte-identical to the old global order.
        self.assertEqual(tiers.candidate_order_sql(), tiers.CANDIDATE_ORDER_SQL)
        self.assertEqual(tiers.candidate_order_sql("s"),
                         tiers.candidate_order_sql("s"))


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


class AudioLanguageTests(unittest.TestCase):
    """Session 71: a rung shows only the audio languages its own print carries."""

    def test_a_pipe_separated_languages_column_becomes_a_list(self):
        tier = tiers.for_release(
            {"quality": "1080p", "languages": "Hindi|Tamil"}, [link()])["tiers"][0]
        self.assertEqual(tier["audio_languages"], ["Hindi", "Tamil"])

    def test_comma_separated_and_duplicate_languages_dedupe(self):
        tier = tiers.for_release(
            {"quality": "720p", "languages": "Hindi, Hindi|English"},
            [link()])["tiers"][0]
        self.assertEqual(tier["audio_languages"], ["Hindi", "English"])

    def test_an_empty_languages_column_yields_no_audio_line(self):
        for languages in (None, "", "  ", ", | ,"):
            tier = tiers.for_release(
                {"quality": "720p", "languages": languages}, [link()])["tiers"][0]
            self.assertEqual(tier["audio_languages"], [], languages)

    def test_merge_keeps_the_winning_prints_languages(self):
        one = tiers.for_release({"quality": "1080p", "languages": "English"},
                                [link(id=1, is_resumable=0)])
        two = tiers.for_release({"quality": "1080p", "languages": "Hindi"},
                                [link(id=2, is_resumable=1)])
        merged = tiers.merge([one, two])
        self.assertEqual(merged["tiers"][0]["link"]["id"], 2)
        self.assertEqual(merged["tiers"][0]["audio_languages"], ["Hindi"])


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

    def test_an_iframe_our_server_can_unwrap_is_resolve_not_external(self):
        # Session 107, Phase D item 6: an iframe with a server-side unwrapper
        # (catalog_v2._SERVER_RESOLVABLE_SERVICES) resolves to a real
        # playlist or file, so the client must resolve it first — and the
        # copy becomes playable, not external. The service name never
        # reaches the response; only the kind changes.
        for service in ("vidrift", "vidbolt", "filmu", "iqsmart", "cineverse",
                        "streamtape", "stream", "streamwish", "mixdrop", "voe",
                        "vidhide", "1xplayer", "uploadflix", "vidout",
                        "mxdrop", "animahd-player"):
            view = viewer.link_view(link(playback_type="iframe", service=service),
                                    "http://our.box")
            self.assertEqual(view["kind"], "resolve", service)
            self.assertTrue(view["playable"], service)
            # The service name itself never reaches the response: no
            # "service" key, and no provenance needle in the payload.
            self.assertNotIn("service", view, service)

    def test_an_iframe_with_no_unwrapper_stays_external(self):
        # vidsrc has no server-side unwrapper at all. (vidout used to be
        # listed here — its playlist host did not resolve on VM DNS — but
        # Phase C item 3 gave it a real chain, so it is "resolve" now and
        # lives in the test above.)
        for service in ("vidsrc",):
            view = viewer.link_view(link(playback_type="iframe", service=service),
                                    "http://our.box")
            self.assertEqual(view["kind"], "external", service)
            self.assertFalse(view["playable"], service)

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


class FailoverTests(unittest.TestCase):
    """Mentor method #1: the winner travels with runner-ups of *its own* band.

    A free CDN answers 403 occasionally. The user must not see a dialog and must
    not drop to another quality, so the same-band copies the collapse folded away
    stay with the tier as silent backups instead of vanishing."""

    def test_a_play_tier_carries_two_runner_ups_of_its_own_band(self):
        ladder = tiers.for_release({"quality": "1080p"}, [
            link(id=1, is_resumable=1), link(id=2), link(id=3), link(id=4)])
        tier = ladder["tiers"][0]
        self.assertEqual(tier["link"]["id"], 1)
        self.assertEqual([item["id"] for item in tier["backups"]], [2, 3])
        self.assertEqual(len(tier["backups"]), tiers.BACKUP_LIMIT)
        self.assertTrue(all(tiers.playable(item, "1080p") for item in tier["backups"]))

    def test_an_embed_copy_is_never_a_backup_of_a_play_tier(self):
        # Hopping from a playing file to a page we can only hand to another app
        # would be a visible downgrade, not a silent failover.
        ladder = tiers.for_release({"quality": "1080p"}, [
            link(id=1, playback_type="direct"), link(id=2, playback_type="iframe"),
            link(id=3, playback_type="iframe")])
        tier = ladder["tiers"][0]
        self.assertEqual(tier["link"]["id"], 1)
        self.assertEqual(tier["backups"], [])

    def test_a_dead_copy_is_no_longer_a_silent_failover_hop(self):
        # Audit critical 10 retired the older expectation ([3, 2]) that kept a
        # dead copy in the last backup slot: a failover hop is a served copy,
        # and nothing that answers dead/broken/gone/expired may be played.
        ladder = tiers.for_release({"quality": "720p"}, [
            link(id=1, is_resumable=1), link(id=2, status="dead"), link(id=3)])
        tier = ladder["tiers"][0]
        self.assertEqual([item["id"] for item in tier["backups"]], [3])

    def test_a_download_only_tier_still_offers_its_other_copies(self):
        ladder = tiers.for_release({"quality": "480p"}, [
            link(id=1, playback_type="download"), link(id=2, playback_type="download"),
            link(id=3, playback_type="download")])
        tier = ladder["tiers"][0]
        self.assertEqual(tier["mode"], "download_only")
        self.assertEqual(len(tier["backups"]), tiers.BACKUP_LIMIT)

    def test_merge_pools_copies_from_every_print_into_one_ladder(self):
        ladders = [tiers.for_release({"quality": "1080p"}, [link(id=i, is_resumable=1)])
                   for i in (1, 2, 3, 4)]
        merged = tiers.merge(ladders)
        tier = merged["tiers"][0]
        self.assertEqual(tier["copies"], 4)
        self.assertNotIn(tier["link"]["id"], [item["id"] for item in tier["backups"]])
        self.assertEqual(len(tier["backups"]), tiers.BACKUP_LIMIT)

    def test_candidate_order_sql_alias_qualifies_columns(self):
        # The cross-release failover joins download_sources to releases,
        # and both tables have id and created_at, so the aliased form
        # must qualify every column — an unqualified one is ambiguous
        # and the query fails.
        aliased = tiers.candidate_order_sql("s")
        self.assertIn("s.", aliased)
        # A bare " id ASC" (space before id) would be ambiguous against
        # releases.id; the qualified form is "s.id ASC", which has no
        # space before the id.
        self.assertNotIn(" id ASC", aliased)
        self.assertNotIn(" created_at", aliased)
        self.assertEqual(tiers.candidate_order_sql(), tiers.CANDIDATE_ORDER_SQL)

    def test_merge_does_not_list_the_same_copy_twice(self):
        # Two prints of one post often hold the very same link row.
        shared = link(id=9, is_resumable=1)
        merged = tiers.merge([tiers.for_release({"quality": "1080p"}, [shared, link(id=8)]),
                              tiers.for_release({"quality": "1080p"}, [dict(shared),
                                                                       link(id=7)])])
        tier = merged["tiers"][0]
        ids = [item["id"] for item in [tier["link"], *tier["backups"]]]
        self.assertEqual(len(ids), len(set(ids)), ids)


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


    def test_the_ladder_travels_with_silent_backup_handles(self):
        # The client fails over without asking: it gets the runner-ups as handles
        # for the same /api/v1/stream door as the winner, never as links of their own.
        post_id = self._save("1080p", [
            {"source_name": f"Mirror {index}", "service": "pixeldrain",
             "resource_id": chr(96 + index), "source_url": f"https://x.example/{index}",
             "final_url": f"https://cdn.example/{index}", "is_temporary": 0}
            for index in (1, 2, 3)])
        viewer.DB_PATH = self.db_path
        tier = viewer.api_v1_get_post_detail(
            post_id, base_url="http://our.box")["option_groups"][0]["tiers"][0]
        self.assertNotIn("backups", tier)
        handles = tier["backup_handles"]
        self.assertEqual(len(handles), tiers.BACKUP_LIMIT)
        self.assertNotIn(tier["link"]["stream_id"], handles)
        self.assertEqual(len(set(handles)), len(handles))
        secret = viewer.signing_secret()
        row_ids = []
        for handle in handles:
            self.assertFalse(str(handle).isdigit())
            row_ids.append(redact.parse_token(handle, secret))
        # Every handle must address a copy this post really has, or the player
        # would "fail over" onto a link that 404s by construction.
        import sqlite3
        with sqlite3.connect(self.db_path) as conn:
            mine = {row[0] for row in conn.execute(
                "SELECT s.id FROM download_sources s JOIN releases r ON r.id = s.release_id"
                " WHERE r.post_id = ?", (post_id,))}
        self.assertTrue(set(row_ids).issubset(mine))
        self.assertNotIn(redact.parse_token(tier["link"]["stream_id"], secret), row_ids)
        blob = str(tier).lower()
        for needle in ("pixeldrain", "hubcloud", "cdn.example", "source_url", "final_url"):
            self.assertNotIn(needle, blob, needle)


class DeadLinkGateTests(unittest.TestCase):
    """Audit critical 10: a dead or expired copy must never win a band, be
    called playable, or be served as a stream — however shiny its other
    evidence is. This was arithmetic, not taste: −60 inside a stack of bonuses
    (kind 100 + active-absent + resumable 15 + HTTP 15 + speed 20) left a dead
    direct link scoring ~90, above a slow live resolve."""

    def test_a_dead_link_scores_zero_however_fast_and_resumable(self):
        fast_dead = link(id=1, status="dead", is_resumable=1, http_status=200,
                         speed_mbps=95, rank_score=200,
                         last_checked_at="2026-10-01 00:00:00")
        self.assertEqual(tiers.score(fast_dead, "1080p"), 0)
        for verdict in ("dead", "broken", "gone"):
            self.assertEqual(tiers.score(link(status=verdict), "1080p"), 0, verdict)

    def test_a_live_slow_link_outscores_a_fast_dead_one(self):
        slow_live = link(id=1, playback_type="url", is_resumable=0)
        fast_dead = link(id=2, status="dead", is_resumable=1, http_status=200,
                         speed_mbps=95, rank_score=200)
        self.assertGreater(tiers.score(slow_live, "1080p"),
                           tiers.score(fast_dead, "1080p"))

    def test_expired_is_penalised_like_a_dead_verdict_but_not_zeroed(self):
        live = link(id=1)
        expired = link(id=2, status="expired", is_resumable=1, http_status=200)
        self.assertLess(tiers.score(expired, "1080p"), tiers.score(live, "1080p"))
        self.assertGreater(tiers.score(expired, "1080p"), 0)

    def test_playable_refuses_every_dead_family_verdict(self):
        for verdict in ("dead", "broken", "gone", "expired"):
            self.assertFalse(tiers.playable(link(status=verdict)), verdict)

    def test_a_stated_verdict_outranks_a_projected_playable_boolean(self):
        # A v2 view may still carry playable=True from an older projection; the
        # link's own state answers first, so a stale boolean cannot play it.
        self.assertFalse(tiers.playable(
            {"kind": "direct", "state": "expired", "playable": True}))
        self.assertFalse(tiers.playable(
            {"kind": "direct", "state": "dead", "playable": True}))

    def test_unprobed_and_live_states_still_play(self):
        for verdict in ("active", "unchecked", "unknown", "", None):
            self.assertTrue(tiers.playable(link(status=verdict)), repr(verdict))

    def test_link_view_marks_a_dead_ledger_row_unplayable(self):
        view = viewer.link_view(link(status="dead"), "http://our.box")
        self.assertFalse(view["playable"])
        view = viewer.link_view(link(status="expired"), "http://our.box")
        self.assertFalse(view["playable"])

    def test_a_dead_direct_never_wins_a_band_against_a_live_resolve(self):
        dead_direct = link(id=1, status="dead", is_resumable=1, http_status=200,
                           speed_mbps=95, rank_score=200)
        live_resolve = link(id=2, playback_type="url")
        ladder = tiers.for_release({"quality": "1080p"}, [dead_direct, live_resolve])
        self.assertEqual(ladder["tiers"][0]["link"]["id"], 2)
        # The dead copy may still trail as a silent runner-up (an existing rule
        # pins dead last in `backups`); what it may no longer be is the winner.
        self.assertEqual(tiers.score(dead_direct, "1080p"), 0)


class AudioTests(unittest.TestCase):
    """Audit #32: a quality row carries the print's audio languages."""

    def test_headline_languages_fill_an_empty_column(self):
        # The Rogmovies shape: the languages live in the headline, not the
        # column — the rung must still say Telugu + Tamil, canonically.
        ladder = tiers.for_release(
            {"quality": "480p",
             "release_title": "Salaar - Part 1 (2023) Multi Audios "
                              "[Tel + Tam + Mal + Kan] NF WeB-DL 480p [700MB]",
             "languages": ""},
            [link()])
        self.assertEqual(ladder["tiers"][0]["audio_languages"],
                         ["Telugu", "Tamil", "Malayalam", "Kannada"])

    def test_stored_column_wins_over_the_headline(self):
        ladder = tiers.for_release(
            {"quality": "720p", "release_title": "X [Tel + Tam]",
             "languages": "Hindi"},
            [link()])
        self.assertEqual(ladder["tiers"][0]["audio_languages"], ["Hindi"])

    def test_json_array_column_parses(self):
        ladder = tiers.for_release(
            {"quality": "720p", "release_title": "X",
             "languages": "[\"Hindi\", \"Tamil\"]"},
            [link()])
        self.assertEqual(ladder["tiers"][0]["audio_languages"],
                         ["Hindi", "Tamil"])

    def test_pipe_column_parses(self):
        ladder = tiers.for_release(
            {"quality": "720p", "release_title": "X",
             "languages": "Hindi|Tamil"},
            [link()])
        self.assertEqual(ladder["tiers"][0]["audio_languages"],
                         ["Hindi", "Tamil"])

    def test_nothing_anywhere_means_no_audio_line(self):
        ladder = tiers.for_release(
            {"quality": "720p", "release_title": "X", "languages": ""},
            [link()])
        self.assertEqual(ladder["tiers"][0]["audio_languages"], [])


if __name__ == "__main__":
    unittest.main()
