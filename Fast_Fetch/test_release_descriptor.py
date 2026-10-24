#!/usr/bin/env python3
"""Offline unit tests for release_descriptor.py — no database, no network."""

import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import release_descriptor as rd

SHIVAAY = "Shivaay (2016) 1080p HEVC x265 10Bit [Hindi DD 5.1 | English] {Full HD}"
LUCIFER = ("Lucifer S04 (2019) (Hindi + English) Dual Audio Completed "
           "Web Series BluRay HEVC ESub")
CAMPUS = ("Campus Beats (2026) Hindi ORG S07EP(01-06) Web Series HDRip "
          "| 1080p | 720p | 480p | Esubs")
DUNE_4K = "Dune (2021) 2160p DV HDR10+ WEB-DL DDP 5.1 Atmos English"
DUNE_FHD = "Dune (2021) 1080p DV HDR10+ WEB-DL DDP 5.1 Atmos English"
AVENGERS = "Avengers Endgame 720p HDRip [Hindi-English] Esubs x264 - ETLEB"
BIGG_BOSS = "Bigg Boss (2026 Grand Premiere) 480p"
DIRECTORS_CUT = "Movie (2024) Director's Cut 1080p BluRay v2 REPACK"


class ReleaseDescriptorTests(unittest.TestCase):
    # ------------------------------------------------------------------ #
    # 1. the full-field reference print
    # ------------------------------------------------------------------ #
    def test_shivaay_1080p_hevc_10bit_dual_audio_surround(self):
        p = rd.describe(SHIVAAY, quality="1080p", codec="HEVC", size="1.2GB",
                        source_site="vegamovies")
        self.assertEqual(sorted(p), sorted(rd.PRINT_KEYS))
        self.assertEqual(p["resolution"], "1080p")
        self.assertEqual(p["quality_label"], "Full HD")
        self.assertEqual(p["source_tag"], "unknown")
        self.assertEqual(p["codec"], "h265")
        self.assertEqual(p["bit_depth"], 10)
        self.assertEqual(p["hdr"], [])
        self.assertEqual(p["container"], "unknown")
        self.assertEqual(p["audio"]["languages"], ["Hindi", "English"])
        self.assertEqual(p["audio"]["channel_layout"], "5.1")
        self.assertEqual(p["audio"]["codecs"], ["dd"])
        self.assertIs(p["audio"]["dual_audio"], True)
        self.assertIs(p["subtitles"]["available"], False)
        self.assertEqual(p["edition"], "unknown")
        self.assertEqual(p["version"], 0)
        self.assertIs(p["is_pack"], False)
        self.assertEqual(p["episode_range"], "")
        self.assertEqual(p["season"], 0)
        self.assertEqual(p["episode"], 0)
        self.assertEqual(p["scope"], "movie")
        self.assertEqual(p["size_bytes"], 1288490189)
        self.assertEqual(p["size_per_episode_bytes"], 0)
        self.assertIs(p["watermarked"], False)
        self.assertIs(p["official_print"], True)
        self.assertEqual(p["title_stub"], "Shivaay")
        # 300 (1080p) + 60 (unknown source) + 30 (h265) + 20 (10-bit)
        # + 40 (official) + 25 (dual audio) + 15 (5.1)
        self.assertEqual(p["quality_score"], 490)

    # ------------------------------------------------------------------ #
    # 2. season pack
    # ------------------------------------------------------------------ #
    def test_lucifer_completed_season_pack(self):
        p = rd.describe(LUCIFER, quality="1080p", codec="HEVC", season="S04",
                        episode="Batch", source_site="hdhub4u")
        self.assertEqual(p["season"], 4)
        self.assertEqual(p["episode"], 0)
        self.assertEqual(p["scope"], "season_pack")
        self.assertEqual(p["source_tag"], "bluray")
        self.assertEqual(p["resolution"], "1080p")
        self.assertEqual(p["codec"], "h265")
        self.assertIs(p["subtitles"]["available"], True)
        self.assertIs(p["subtitles"]["external"], True)
        self.assertIs(p["subtitles"]["hardcoded"], False)
        self.assertEqual(p["subtitles"]["langs"], ["English"])
        self.assertIs(p["is_pack"], True)
        self.assertEqual(p["episode_range"], "")
        self.assertIs(p["official_print"], True)
        self.assertEqual(p["audio"]["dual_audio"], True)
        self.assertEqual(p["title_stub"], "Lucifer")
        self.assertEqual(p["quality_score"], 695)

    # ------------------------------------------------------------------ #
    # 3. episode range, best of several resolutions named on one label
    # ------------------------------------------------------------------ #
    def test_campus_beats_episode_range_and_best_resolution(self):
        p = rd.describe(CAMPUS, quality="unknown", size="300MB/E")
        self.assertEqual(p["episode_range"], "1-6")
        self.assertEqual(p["scope"], "episode_range")
        self.assertEqual(p["resolution"], "1080p")
        self.assertEqual(p["quality_label"], "Full HD")
        self.assertEqual(p["season"], 7)
        self.assertEqual(p["episode"], 0)
        self.assertIs(p["is_pack"], True)
        self.assertEqual(p["source_tag"], "dvdrip")
        self.assertEqual(p["audio"]["languages"], ["Hindi"])
        self.assertEqual(p["size_bytes"], 0)
        self.assertEqual(p["size_per_episode_bytes"], 314572800)
        self.assertEqual(p["title_stub"], "Campus Beats")
        best = rd.combined_quality_score(resolution="1080p", source_tag="dvdrip",
                                         official_print=True,
                                         subtitles={"external": True})
        worst = rd.combined_quality_score(resolution="480p", source_tag="dvdrip",
                                          official_print=True,
                                          subtitles={"external": True})
        self.assertEqual(p["quality_score"], best)
        self.assertGreater(p["quality_score"], worst)

    # ------------------------------------------------------------------ #
    # 4. 4K Dolby Vision + HDR10+, and explicit monotonicity
    # ------------------------------------------------------------------ #
    def test_dune_dolby_vision_and_hdr10_plus_not_plain_hdr10(self):
        p = rd.describe(DUNE_4K, quality="2160p")
        self.assertEqual(p["hdr"], ["dolby_vision", "hdr10_plus"])
        self.assertNotIn("hdr10", p["hdr"])
        self.assertEqual(p["resolution"], "2160p")
        self.assertEqual(p["quality_label"], "4K UHD")
        self.assertEqual(p["source_tag"], "web_dl")
        self.assertEqual(p["codec"], "unknown")
        self.assertEqual(p["bit_depth"], 0)
        self.assertEqual(p["audio"]["codecs"], ["ddp", "atmos"])
        self.assertEqual(p["audio"]["channel_layout"], "5.1")
        self.assertEqual(p["audio"]["languages"], ["English"])
        self.assertEqual(p["edition"], "unknown")
        self.assertEqual(p["scope"], "movie")
        self.assertEqual(p["title_stub"], "Dune")
        lower = rd.describe(DUNE_FHD, quality="1080p")
        self.assertEqual(p["quality_score"], 755)
        self.assertEqual(lower["quality_score"], 655)
        self.assertGreater(p["quality_score"], lower["quality_score"])
        # HDR10+ on its own is still HDR, so it earns the same +60 bonus.
        plus_only = rd.describe("Interstellar (2014) 1080p BluRay HDR10+ x265")
        self.assertEqual(plus_only["hdr"], ["hdr10_plus"])
        self.assertNotIn("hdr10", plus_only["hdr"])
        self.assertEqual(plus_only["quality_score"], 300 + 280 + 60 + 30 + 40)

    # ------------------------------------------------------------------ #
    # 5. watermarked print is penalised and never official
    # ------------------------------------------------------------------ #
    def test_etlab_watermark_penalises_and_disqualifies(self):
        p = rd.describe(AVENGERS, quality="720p", codec="x264")
        self.assertIs(p["watermarked"], True)
        self.assertIs(p["official_print"], False)
        self.assertEqual(p["resolution"], "720p")
        self.assertEqual(p["source_tag"], "dvdrip")
        self.assertEqual(p["codec"], "h264")
        self.assertEqual(p["audio"]["languages"], ["Hindi", "English"])
        self.assertIs(p["subtitles"]["external"], True)
        clean = rd.describe(AVENGERS.replace(" - ETLEB", ""), quality="720p",
                            codec="x264")
        self.assertIs(clean["watermarked"], False)
        self.assertIs(clean["official_print"], True)
        self.assertLess(p["quality_score"], clean["quality_score"])
        self.assertEqual(clean["quality_score"] - p["quality_score"], 100)

    # ------------------------------------------------------------------ #
    # 6. episodic label without season/episode numbers
    # ------------------------------------------------------------------ #
    def test_bigg_boss_premiere_is_not_called_a_movie(self):
        p = rd.describe(BIGG_BOSS, quality="480p")
        self.assertEqual(p["resolution"], "480p")
        self.assertEqual(p["quality_label"], "SD")
        self.assertEqual(p["scope"], "unknown")
        self.assertEqual(p["edition"], "unknown")
        self.assertEqual(p["source_tag"], "unknown")
        self.assertEqual(p["codec"], "unknown")
        self.assertEqual(p["bit_depth"], 0)
        self.assertEqual(p["hdr"], [])
        self.assertEqual(p["container"], "unknown")
        self.assertEqual(p["audio"]["languages"], [])
        self.assertEqual(p["audio"]["channel_layout"], "unknown")
        self.assertIs(p["audio"]["dual_audio"], False)
        self.assertIs(p["subtitles"]["available"], False)
        self.assertEqual(p["season"], 0)
        self.assertEqual(p["episode"], 0)
        self.assertIs(p["is_pack"], False)
        self.assertEqual(p["size_bytes"], 0)
        self.assertIs(p["watermarked"], False)
        self.assertEqual(p["quality_score"], 220)

    # ------------------------------------------------------------------ #
    # 7. edition + version, and REPACK must not read as a pack
    # ------------------------------------------------------------------ #
    def test_directors_cut_version_and_repack_is_not_a_pack(self):
        p = rd.describe(DIRECTORS_CUT, quality="1080p")
        self.assertEqual(p["edition"], "director_cut")
        self.assertEqual(p["version"], 2)
        self.assertIs(p["is_pack"], False)
        self.assertEqual(p["source_tag"], "bluray")
        self.assertIs(p["official_print"], True)
        self.assertEqual(p["title_stub"], "Movie")
        self.assertEqual(p["quality_score"], 635)

    # ------------------------------------------------------------------ #
    # 8. size table
    # ------------------------------------------------------------------ #
    def test_size_table_exact_bytes(self):
        table = (
            ("400MB", 419430400, 0),
            ("1.2GB", 1288490189, 0),
            ("2.24 GB", 2405181686, 0),
            ("400.00 MB", 419430400, 0),
            ("1.5 GB", 1610612736, 0),
            ("500 KB", 512000, 0),
            ("150MB/E", 0, 157286400),
            ("300 MB / Ep", 0, 314572800),
            ("1 GB", 1073741824, 0),
            ("junk", 0, 0),
            ("", 0, 0),
        )
        for text, total, per_episode in table:
            p = rd.describe("Kabir Singh (2019) 1080p HEVC x265", size=text)
            with self.subTest(size=text):
                self.assertEqual(p["size_bytes"], total)
                self.assertEqual(p["size_per_episode_bytes"], per_episode)

    # ------------------------------------------------------------------ #
    # 9. case / separator / unicode robustness
    # ------------------------------------------------------------------ #
    def test_case_and_separator_robustness(self):
        for quality in ("1080P", "1080p", "  1080p  "):
            self.assertEqual(rd.describe("Z (2020)", quality=quality)["resolution"], "1080p")
        for tag in ("WEB-DL", "Web DL", "webdl", "web  dl"):
            with self.subTest(tag=tag):
                self.assertEqual(rd.describe(f"Z (2020) 1080p {tag}")["source_tag"], "web_dl")
        for codec, depth in (("HEVC 10 bit", 10), ("H.265", 0), ("x265-10Bit", 10),
                             ("10BIT HEVC", 10), ("HEVC x265 8bit", 8)):
            p = rd.describe(f"Z (2020) 1080p {codec}")
            with self.subTest(codec=codec):
                self.assertEqual(p["codec"], "h265")
                self.assertEqual(p["bit_depth"], depth)
        for subs in ("ESub", "eSubs", "ESubs", "Eng Sub"):
            p = rd.describe(f"Z (2020) 1080p WEBRip {subs}")
            with self.subTest(subs=subs):
                self.assertIs(p["subtitles"]["external"], True)
                self.assertEqual(p["subtitles"]["langs"], ["English"])
        unicode_label = rd.describe("Z (2020) 1080p\u2013HEVC 10\u2011bit WEB\u2013DL")
        self.assertEqual(unicode_label["resolution"], "1080p")
        self.assertEqual(unicode_label["codec"], "h265")
        self.assertEqual(unicode_label["source_tag"], "web_dl")
        spaced = rd.describe("Z    (2020)\t1080p   x264\nMKV")
        self.assertEqual(spaced["codec"], "h264")
        self.assertEqual(spaced["container"], "mkv")
        # `title_stub` keeps the human title and drops everything a detector ate.
        stubs = (("Shivaay (2018) 1080p HEVC x265 10Bit [HINDI ENGLISH] DDP 5.1 ESubs.mkv",
                  "Shivaay"),
                 ("Lucifer S04E01 to E06 (2026) 1080p WEB-DL x265", "Lucifer"),
                 ("Dune Part Two (2024) 2160p HDR10+ TrueHD Atmos", "Dune Part Two"),
                 ("Vikram (2022) 1080p WEB-DL Tamil Hindi HardSubs", "Vikram"))
        for label, expected in stubs:
            with self.subTest(label=label):
                self.assertEqual(rd.describe(label)["title_stub"], expected)
        lossless = rd.describe("Coven (2023) 2160p BluRay TrueHD Atmos 7.1")
        self.assertEqual(lossless["audio"]["codecs"], ["truehd", "atmos"])
        self.assertEqual(lossless["audio"]["channel_layout"], "5.1")
        self.assertEqual(lossless["hdr"], [])

    # ------------------------------------------------------------------ #
    # 10. pathological input must never raise
    # ------------------------------------------------------------------ #
    def test_pathological_input_returns_a_complete_print(self):
        junk = [
            {}, {"release_title": ""}, {"release_title": "   "},
            {"release_title": None, "quality": None, "codec": None},
            {"release_title": "((("}, {"release_title": ")))"},
            {"release_title": "(((S01)))"}, {"release_title": "[[]]{{}}"},
            {"release_title": "()()()"}, {"release_title": "|"}, {"release_title": "|||---"},
            {"release_title": "\n\n\t\t"}, {"release_title": "\x00\x01"},
            {"release_title": "1080p" * 1200}, {"release_title": "EP(" * 900},
            {"release_title": "E" + "9" * 900}, {"release_title": "S" * 5000},
            {"release_title": "s01e" + "-" * 800}, {"release_title": "0.0.0.0 MB GB TB"},
            {"release_title": "1e9-2e10", "size": "1e9"},
            {"release_title": "Hindi", "languages": "Tamil", "season": "S",
             "episode": "E"},
            {"season": "-1", "episode": "999999999999"}, {"size": "MB"},
            {"size": "99999999999999999999999GB"}, {"codec": "265", "quality": "264"},
            {"release_title": "_HDR10+++", "quality": "DV"},
            {"release_title": "CAM CAM CAM", "quality": "480p", "source_site": "x"},
            {"release_title": "v999 v0", "quality": "720p-HEVC"},
            {"release_title": "\u2013" * 300, "size": "\u2013"},
            {"release_title": "Season 99999 Episodes 88888-77777"},
        ]
        for kwargs in junk:
            with self.subTest(label=str(kwargs)[:60]):
                p = rd.describe(**kwargs)
                self.assertIsInstance(p, dict)
                self.assertEqual(sorted(p), sorted(rd.PRINT_KEYS))
                self.assertNotIn(None, p.values())
                self.assertTrue(0 <= p["quality_score"] <= 1000)
                self.assertIsInstance(p["hdr"], list)
                self.assertIsInstance(p["audio"]["languages"], list)
                self.assertIsInstance(p["is_pack"], bool)

    # ------------------------------------------------------------------ #
    # 11. the ladder is a strict total order
    # ------------------------------------------------------------------ #
    def test_quality_ladder_is_strictly_increasing(self):
        ladder = [
            "Scream 2024 480p CAM",
            "Scream 2024 480p WEBRip",
            "Scream 2024 720p WEBRip",
            "Scream 2024 1080p WEB-DL",
            "Scream 2024 1080p BluRay",
            "Scream 2024 2160p BluRay",
        ]
        scores = [rd.describe(label)["quality_score"] for label in ladder]
        self.assertEqual(scores, sorted(scores))
        self.assertTrue(all(a < b for a, b in zip(scores, scores[1:])))
        self.assertEqual(scores[0], 140)
        self.assertEqual(scores[-1], 740)
        self.assertLessEqual(rd.describe("Scream 2024 2160p CAM")["quality_score"], 250)
        self.assertEqual([rd.resolution_rank(r) for r, _ in rd.QUALITY_LADDER],
                         sorted(rd.resolution_rank(r) for r, _ in rd.QUALITY_LADDER))
        self.assertEqual(rd.resolution_rank("unknown"), 50)
        self.assertEqual(rd.source_rank("uhd_bluray"), 300)
        self.assertEqual(rd.source_rank("nonsense"), rd.source_rank("unknown"))

    # ------------------------------------------------------------------ #
    # 12. codec must survive a quality-only column
    # ------------------------------------------------------------------ #
    def test_codec_recovered_when_only_quality_column_names_it(self):
        p = rd.describe("Kabir Singh (2019)", quality="720p-HEVC", codec="")
        self.assertEqual(p["resolution"], "720p")
        self.assertEqual(p["codec"], "h265")
        self.assertEqual(p["source_tag"], "unknown")
        q = rd.describe("Kabir Singh (2019)", quality="1080p-HEVC 10bit", codec="")
        self.assertEqual(q["codec"], "h265")
        self.assertEqual(q["bit_depth"], 10)
        r = rd.describe("Kabir Singh (2019)", quality="1080p-WEB-DL", codec="")
        self.assertEqual(r["source_tag"], "web_dl")
        self.assertIs(r["official_print"], True)
        s = rd.describe("Kabir Singh (2019)", quality="2160p-HEVC", codec="")
        self.assertEqual(s["source_tag"], "unknown")
        self.assertEqual(s["quality_label"], "4K UHD")
        t = rd.describe("Kabir Singh (2019)", quality="4k-HEVC", codec="")
        self.assertEqual(t["resolution"], "2160p")
        self.assertEqual(t["codec"], "h265")

    # ------------------------------------------------------------------ #
    # extras: every remaining documented field has an owner
    # ------------------------------------------------------------------ #
    def test_bare_hd_is_a_label_not_a_resolution(self):
        p = rd.describe("Inception (2010) HD", quality="HD")
        self.assertEqual(p["resolution"], "unknown")
        self.assertEqual(p["quality_label"], "HD")
        self.assertEqual(p["source_tag"], "unknown")
        self.assertIs(p["official_print"], False)
        self.assertEqual(p["quality_score"], 110)

    def test_container_bit_depth_and_edition_variants(self):
        table = (
            ("A (2020) 1080p BluRay x265.mkv", "mkv"),
            ("A (2020) 1080p WEB-DL.mp4", "mp4"),
            ("A (2020) 720p BDRip xvid.avi", "avi"),
            ("A (2020) 1080p HDRip ProRes.MOV", "mov"),
            ("A (2020) 1080p HDTV AVC.ts", "ts"),
            ("A (2020) 1080p HDTV AVC", "unknown"),
        )
        for label, container in table:
            with self.subTest(label=label):
                self.assertEqual(rd.describe(label)["container"], container)
        self.assertEqual(rd.describe("A (2020) 1080p BluRay x265 12bit")["bit_depth"], 12)
        self.assertEqual(rd.describe("A (2020) 1080p BluRay x264 8bit")["bit_depth"], 8)
        editions = {
            "A (2020) 1080p BluRay Extended Cut": "extended",
            "A (2020) 1080p BluRay UNRATED": "unrated",
            "A (2020) 2160p BluRay Remastered": "remastered",
            "A (2020) 1080p DVD5 Restored": "restored",
            "A (2020) 1080p BluRay Uncut": "uncut",
            "A (2020) 1080p IMAX WEB-DL": "imax",
            "A (2020) 1080p BluRay Theatrical Cut": "theatrical",
            "A (2020) 720p CAM Fan Edit": "fan_edit",
        }
        for label, edition in editions.items():
            with self.subTest(label=label):
                self.assertEqual(rd.describe(label)["edition"], edition)
        fan = rd.describe("A (2020) 1080p BluRay Fan Edit")
        self.assertIs(fan["official_print"], False)

    def test_hardcoded_subtitles_and_dual_audio_flags(self):
        p = rd.describe("Vikram (2022) 1080p WEB-DL Tamil Hindi HardSubs")
        self.assertIs(p["subtitles"]["available"], True)
        self.assertIs(p["subtitles"]["hardcoded"], True)
        self.assertIs(p["subtitles"]["external"], False)
        q = rd.describe("Vikram (2022) 1080p WEB-DL Multi Audio ESubs")
        self.assertIs(q["audio"]["dual_audio"], True)
        self.assertIs(q["subtitles"]["external"], True)
        self.assertEqual(q["audio"]["codecs"], [])
        self.assertGreater(q["quality_score"], p["quality_score"])

    def test_scope_variants_and_episode_range_forms(self):
        single = rd.describe("Flip S02E05 (2023) 1080p WEB-DL", season="S02",
                             episode="E05")
        self.assertEqual((single["scope"], single["season"], single["episode"],
                          single["is_pack"]), ("episode", 2, 5, False))
        batched = rd.describe("Flip S02 (2023) 1080p WEB-DL Batch", season="S02",
                              episode="Batch")
        self.assertEqual((batched["scope"], batched["is_pack"]), ("season_pack", True))
        ranges = {
            "Flip (2023) WEB-DL E01-04": "1-4",
            "Flip (2023) WEB-DL Episodes 1-12": "1-12",
            "Flip S04E01 to E06 WEB-DL": "1-6",
            "Flip (2023) EP(07-12) WEB-DL": "7-12",
        }
        for label, expected in ranges.items():
            p = rd.describe(label)
            with self.subTest(label=label):
                self.assertEqual(p["episode_range"], expected)
                self.assertEqual(p["scope"], "episode_range")
                self.assertIs(p["is_pack"], True)
                self.assertEqual(p["episode"], 0)
        self.assertEqual(rd.describe("Ringa (2019) Season 1-3 Collection 1080p")[
            "scope"], "multi_season")
        self.assertEqual(rd.describe("Chernobyl (2019) 1080p WEB-DL Mini Series")[
            "scope"], "miniseries")

    def test_every_watermark_marker_is_recognised(self):
        for marker in rd.WATERMARK_MARKERS:
            p = rd.describe(f"Masaan (2015) 1080p WEB-DL x265 {marker}")
            with self.subTest(marker=marker):
                self.assertIs(p["watermarked"], True)
                self.assertIs(p["official_print"], False)

    # ------------------------------------------------------------------ #
    # 13. HDTC is a cam-family capture, never an official print (API_V2 §18 G-4)
    # ------------------------------------------------------------------ #
    def test_hdtc_is_capped_cam_family_never_official(self):
        for spelling in ("HDTC", "hdtc", "H-DTC", "HD-TC", "H.D.TC", "Hdtc"):
            p = rd.describe(f"Scream (2024) 1080p {spelling} x265")
            with self.subTest(spelling=spelling):
                self.assertEqual(p["source_tag"], "hdtc")
                self.assertIs(p["official_print"], False)
                self.assertLessEqual(p["quality_score"], rd.CAM_FAMILY_CEILING)
                self.assertEqual(p["quality_label"], "CAM")
        # Even the most bonus-rich HDTC print stays under the cam ceiling:
        # 300 + 75 + 30 (h265) + 60 (HDR at 1080p) + 40 (would-be official) ... capped.
        rich = rd.describe("Scream (2024) 2160p HDTC x265 HDR10 10Bit ESubs Dual Audio DD 5.1")
        self.assertEqual(rich["source_tag"], "hdtc")
        self.assertIs(rich["official_print"], False)
        self.assertLessEqual(rich["quality_score"], 250)
        # HDTS is HD-Telesync, a different capture: it still reads `telesync`.
        self.assertEqual(rd.describe("Scream (2024) 1080p HDTS x265")["source_tag"], "telesync")

    def test_hdtc_print_ranks_below_a_bare_720p_webrip(self):
        # The ordering claim is the point of the G-4 fix: an HDTC cam rip must
        # never outrank an honest distribution print.
        hdtc = rd.describe("Scream (2024) 1080p HDTC x265")
        webrip = rd.describe("Scream (2024) 720p WEBRip")
        self.assertEqual(hdtc["quality_score"], 250)          # 300+75+30 capped
        self.assertEqual(webrip["quality_score"], 460)        # 200+220+40 floor
        self.assertLess(hdtc["quality_score"], webrip["quality_score"])
        self.assertIs(webrip["official_print"], True)

    # ------------------------------------------------------------------ #
    # 14. conservative SCENE group recovery (additional parsed field only)
    # ------------------------------------------------------------------ #
    def test_release_group_is_a_print_key(self):
        self.assertIn("release_group", rd.PRINT_KEYS)
        self.assertEqual(rd.describe("Bad input ((")["release_group"], "")

    def test_bare_upper_token_after_the_codec_is_the_group(self):
        p = rd.describe("Dune (2024) 1080p WEB-DL x265 GROUP")
        self.assertEqual(p["release_group"], "GROUP")
        dash = rd.describe("Dune.2024.1080p.WEB-DL.x265-GROUP")
        self.assertEqual(dash["release_group"], "GROUP")
        bracketed = rd.describe("Dune (2024) [ETRG] 1080p WEB-DL")
        self.assertEqual(bracketed["release_group"], "ETRG")
        before_res = rd.describe("Vikram BLACK 1080p WEB-DL x265")
        self.assertEqual(before_res["release_group"], "BLACK")
        # Zero Data Loss: the label is never rewritten, the stub keeps its words.
        self.assertIn("GROUP", dash["title_stub"])

    def test_quality_and_version_words_never_become_a_group(self):
        rejects = (
            "Movie (2024) 1080p WEB-DL -x265",
            "Movie (2024) 1080p WEB-DL -ESubs",
            "Movie (2024) 1080p WEB-DL -ESUBS",
            "Movie (2024) 1080p WEB-DL -MULTI",
            "Movie (2024) 1080p WEB-DL MULTISUBS",
            "Movie (2024) 1080p WEB-DL HDCAM",
            "Movie (2024) 1080p WEB-DL HDR",
            "Movie (2024) 1080p WEB-DL DDP5.1",
            "Movie (2024) 1080p WEB-DL x265 REPACK v2",
            "Movie (2024) 1080p WEB-DL x265 REPACK PROPER V2",
            "Dune (2024) 2160p UHD BluRay x265 DDP5.1 -NOGRP",
            "Movie (2024) 1080p WEB-DL",
            "Dune (2024) 2160p WEB-DL x265 GROUP".replace("GROUP", "group"),
            "Kill Book Two (2004) 1080p WEB-DL Part 2",
            "Show S01E05 (2023) 1080p WEB-DL",
            # Real corpus titles: hyphenated names, not release suffixes.
            "CHIP-IN", "86 EIGHTY-SIX", "CO-ED", "BAT-FAM", "MECH-X4",
            "Your Honor (IN)", "Kalki 2898 - AD", "Fukrey 3 (2023) HDTC CAM",
            "Killer Ratings (Season-1) Hindi 720p (Episode 1-7) [550MB] - S01E01",
            "The New Mutants (2020) Dual Audio [Hindi Dubbed (Unofficial VO) + English (ORG)]",
        )
        for label in rejects:
            p = rd.describe(label)
            with self.subTest(label=label):
                self.assertEqual(p["release_group"], "")
        # The watermark suffix from the corpus fixture is a watermark, not a group.
        self.assertEqual(rd.describe(AVENGERS)["release_group"], "")

    def test_groupless_and_plain_title_labels_stay_empty(self):
        for label in ("Inception", "Shivaay (2016)", "",
                      "Movie (2024) WEB-DL 1080p x265"):
            # `WEB-DL` sits before the resolution but is not a single upper-case
            # token, so nothing is guessed.
            with self.subTest(label=label):
                self.assertEqual(rd.describe(label)["release_group"], "")


    def test_language_column_is_merged_and_scoring_bounds(self):
        p = rd.describe("Okja (2017) 1080p WEB-DL", languages="Korean English")
        self.assertEqual(p["audio"]["languages"], ["Korean", "English"])
        self.assertIs(p["audio"]["dual_audio"], True)
        # The best print the ladder can describe: 400+300+60+30+30+40+20+25+15+15.
        self.assertEqual(rd.combined_quality_score(resolution="2160p",
                                                   source_tag="uhd_bluray",
                                                   hdr=["dolby_vision"],
                                                   bit_depth=12, codec="av1",
                                                   official_print=True,
                                                   subtitles={"external": True},
                                                   audio={"dual_audio": True,
                                                          "channel_layout": "5.1"},
                                                   edition="director_cut"), 935)
        self.assertLessEqual(935, 1000)
        # A cam that is also watermarked cannot go below the documented floor.
        self.assertEqual(rd.combined_quality_score(resolution="unknown",
                                                   source_tag="cam",
                                                   watermarked=True), 10)
        self.assertEqual(rd.combined_quality_score(), 110)


if __name__ == "__main__":
    unittest.main(verbosity=2)
