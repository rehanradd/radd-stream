#!/usr/bin/env python3
"""
test_archive_import.py — offline unit tests for the archive.org importer.

No test touches the network: every fetch is a fake and every fixture is
shaped from pages measured live on this host on 2026-11-09 (the proof run
in ``hidden_files/legal-catalog-proof-20261109.md`` plus a same-day live
re-probe of the six known identifiers). The rules this suite keeps, and
the measured defect each one exists because of:

* the license gate denies on the URL, allowlist-first is wrong: a BY-NC-SA
  URL contains both "by-nc" and "by-sa", and the NC half is what decides
  it — the deny markers are checked before any allow marker. Karate
  Warriors 1976 plays fine (Range 206 + ffprobe h264 + audio) but is CC
  BY-NC 4.0: "plays" != "importable" into a monetized app.
* the old public-domain dedication URL
  (``http://creativecommons.org/licenses/publicdomain/``) is ALLOW, not
  unknown: Things To Come 1936 carries exactly that string, and a
  normalizer that only knew ``/publicdomain/mark/`` would have dropped a
  public-domain film.
* ``files[].format`` is not a mp4 detector: the same collection returns
  MPEG4, h.264, 512Kb MPEG4 and h.264 IA for .mp4 files. Matching the
  filename suffix is the only rule that holds.
* a Range probe must see 206, not 200: Archive answers the download URL
  with a 302 to a storage node first, and a no-follow 302 already carries
  ``Content-Type: video/mp4`` — status alone proves nothing, and a 200
  (Range ignored) proves nothing either.
* ffprobe is the second half of the proof, and a missing binary fails
  closed: a row without probe evidence must never be marked playable, so
  ``probe_ffprobe`` returning None skips the item instead of importing
  it on the Range result alone.
* Bowery at Midnight carries two 1.27 GB files that are the same encode
  (plain .mp4 + .ia.mp4, identical size): storing both buys nothing, so
  a >1 GB .ia.mp4 is dropped when a plain .mp4 already probes >=720p.
* ``naked`` is deliberately NOT a review token: The Naked City (1948),
  The Naked Gun and Naked Lunch are mainstream films, and a review flag
  that fires on them is noise. The list names acts/studios only.
* ``sex`` is word-boundary matched: it must never fire inside "Sussex".
* year fallback order is metadata, then identifier, then title — Bogard
  has no year in metadata but carries 1975 in both its identifier and
  its title, and a missing year is stored NULL, never invented.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))

import import_archive as arc  # noqa: E402

PD_MARK = "http://creativecommons.org/publicdomain/mark/1.0/"
PD_MARK_HTTPS = "https://creativecommons.org/publicdomain/mark/1.0/"
PD_OLD = "http://creativecommons.org/licenses/publicdomain/"
CC0 = "https://creativecommons.org/publicdomain/zero/1.0/"
CC_BY = "https://creativecommons.org/licenses/by/4.0/"
CC_BY_SA = "https://creativecommons.org/licenses/by-sa/4.0/"
CC_BY_NC = "https://creativecommons.org/licenses/by-nc/4.0/"
CC_BY_NC_SA = "https://creativecommons.org/licenses/by-nc-sa/4.0/"
CC_BY_ND = "https://creativecommons.org/licenses/by-nd/4.0/"
SAMPLING = "https://creativecommons.org/licenses/sampling/1.0/"


def golf_meta(**over):
    meta = {
        "title": "The Golfers (Andy Clyde Thelma Hill)",
        "year": 1929,
        "licenseurl": PD_MARK,
        "creator": "Mack Sennett",
        "language": "English",
        "subject": ["feature films", "comedy", "short"],
        "description": "A 1929 comedy short.",
    }
    meta.update(over)
    return meta


def golf_files():
    return [{"name": "The Golfers.mp4", "format": "MPEG4", "size": "633389780"},
            {"name": "__ia_thumb.jpg", "format": "Thumbnail", "size": "12345"}]


def range_ok(url):
    return {"ok": True, "status": 206, "content_type": "video/mp4"}


def range_fail(url):
    return {"ok": False, "status": 404, "content_type": ""}


def ffprobe_width(width, height=480, duration=3600.0):
    def _probe(url):
        return {"width": width, "height": height, "codec": "h264",
                "duration": duration, "has_audio": True}
    return _probe


def ffprobe_none(url):
    return None


class FakeResp:
    """Minimal urlopen response: status + headers + context manager."""

    def __init__(self, status=206, content_type="video/mp4"):
        self.status = status
        self.headers = {"Content-Type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class LicenseGateTests(unittest.TestCase):
    def test_pd_mark_http_and_https_allow(self):
        for url in (PD_MARK, PD_MARK_HTTPS):
            verdict, kind, share = arc.classify_license(url)
            self.assertEqual((verdict, kind, share), ("allow", "pd_mark", False))

    def test_old_publicdomain_dedication_allows(self):
        verdict, kind, share = arc.classify_license(PD_OLD)
        self.assertEqual((verdict, kind, share), ("allow", "publicdomain", False))

    def test_cc0_allows(self):
        verdict, kind, share = arc.classify_license(CC0)
        self.assertEqual((verdict, kind), ("allow", "cc0"))

    def test_cc_by_allows_any_version(self):
        verdict, kind, share = arc.classify_license(
            "https://creativecommons.org/licenses/by/3.0/")
        self.assertEqual((verdict, kind, share), ("allow", "cc_by", False))

    def test_cc_by_sa_allows_and_records_share_alike(self):
        verdict, kind, share = arc.classify_license(CC_BY_SA)
        self.assertEqual((verdict, kind, share), ("allow", "cc_by_sa", True))

    def test_cc_by_nc_denies(self):
        self.assertEqual(arc.classify_license(CC_BY_NC)[0], "deny")

    def test_cc_by_nc_sa_denies_despite_the_sa_half(self):
        # The deny markers run first: a BY-NC-SA URL contains "by-sa" too,
        # and the NC half is what decides it.
        self.assertEqual(arc.classify_license(CC_BY_NC_SA)[0], "deny")

    def test_cc_by_nd_denies(self):
        self.assertEqual(arc.classify_license(CC_BY_ND)[0], "deny")

    def test_sampling_denies(self):
        self.assertEqual(arc.classify_license(SAMPLING)[0], "deny")

    def test_unknown_license_denies(self):
        self.assertEqual(
            arc.classify_license("https://example.com/some-license")[0], "deny")

    def test_missing_license_denies(self):
        for missing in (None, "", "   ", []):
            self.assertEqual(arc.classify_license(missing)[0], "deny",
                             "missing license must deny: %r" % (missing,))

    def test_list_form_license_takes_the_first(self):
        verdict, kind, _ = arc.classify_license([PD_MARK])
        self.assertEqual((verdict, kind), ("allow", "pd_mark"))


class ContentScreenTests(unittest.TestCase):
    def test_bondage_in_identifier_flags(self):
        self.assertEqual(arc.needs_review("blondeinbondage", "blondeinbondage"),
                         "bondage")

    def test_mainstream_titles_stay_clean(self):
        for title in ("The Golfers", "Things To Come", "Bowery at Midnight"):
            self.assertIsNone(arc.needs_review(title, "some-id"), title)

    def test_sex_never_fires_inside_sussex(self):
        self.assertIsNone(arc.needs_review("Sussex", "sussex-1940"))

    def test_nudist_flags(self):
        # Measured on the live batch: Diary of a Nudist (1961) is a
        # nudist-camp film that the first wordlist missed — "nudist" names
        # a person-type, and no mainstream word contains it.
        self.assertEqual(arc.needs_review("Diary of a Nudist", "DiaryofaNudist"),
                         "nudist")

    def test_naked_is_not_a_review_token(self):
        # Deliberate: The Naked City (1948), The Naked Gun, Naked Lunch are
        # mainstream films — flagging them would be noise, not signal.
        for title in ("The Naked City", "The Naked Gun", "Naked Lunch"):
            self.assertIsNone(arc.needs_review(title, "naked-city"), title)

    def test_adult_word_boundary(self):
        self.assertEqual(arc.needs_review("Adult Only", "adult-only"), "adult")
        # The boundary rule is the repo's adult law, not a shortcut: the
        # plural "Adults" does not match the singular token, and neither
        # does "Adulterated".
        self.assertIsNone(arc.needs_review("Adults Only", "adults-only"))
        self.assertIsNone(arc.needs_review("Adulterated", "adulterated"))

    def test_short_tokens_never_fire_inside_identifier_words(self):
        # "sex" inside "sussex", "adult" inside "adultery": the identifier
        # match is substring-only on the long act-naming tokens.
        self.assertIsNone(arc.needs_review("Sussex", "sussex-1940"))
        self.assertIsNone(arc.needs_review("Adultery", "adultery-1940"))


class TitleYearTests(unittest.TestCase):
    def test_trailing_year_paren_stripped(self):
        self.assertEqual(arc._clean_title("Bowery at Midnight (1942)"),
                         "Bowery at Midnight")

    def test_trailing_cast_paren_stripped(self):
        self.assertEqual(arc._clean_title("The Golfers (Andy Clyde Thelma Hill)"),
                         "The Golfers")

    def test_digit_paren_is_part_of_the_title(self):
        self.assertEqual(arc._clean_title("My Film (Part 2)"), "My Film (Part 2)")

    def test_year_from_metadata(self):
        self.assertEqual(arc._year_of({"year": 1929}, "x", "The Golfers"), 1929)

    def test_year_from_identifier_when_metadata_has_none(self):
        self.assertEqual(arc._year_of({"year": None}, "bogard-1975", "Bogard (1975)"),
                         1975)

    def test_year_from_title_when_identifier_has_none(self):
        self.assertEqual(arc._year_of({}, "bogard", "Bogard (1975)"), 1975)

    def test_metadata_year_wins_over_identifier(self):
        self.assertEqual(arc._year_of({"year": 1936}, "things-1900", "Things"), 1936)

    def test_no_year_anywhere_is_none_never_invented(self):
        self.assertIsNone(arc._year_of({}, "bogard", "Bogard"))


class QualityBandTests(unittest.TestCase):
    def test_band_is_height_not_width(self):
        # The "p" in 1080p names the vertical resolution. Sita Sings the
        # Blues ships a 1280x720 file: 720p by height, and a width rule
        # would have mislabelled it 1080p — a VIP-gated band — and answered
        # 402 to free users for a free 720p file (measured 2026-11-09).
        self.assertEqual(arc.quality_band(1280, 720), "720p")
        self.assertEqual(arc.quality_band(1920, 1080), "1080p")
        self.assertEqual(arc.quality_band(1556, 1080), "1080p")

    def test_band_boundaries(self):
        cases = [((1920, 1080), "1080p"), ((1280, 1079), "720p"),
                 ((1280, 720), "720p"), ((960, 720), "720p"),
                 ((848, 480), "480p"), ((720, 719), "480p"),
                 ((640, 480), "480p")]
        for (width, height), band in cases:
            self.assertEqual(arc.quality_band(width, height), band,
                             "resolution %dx%d" % (width, height))

    def test_width_fallback_when_no_height_recorded(self):
        self.assertEqual(arc.quality_band(1280, None), "1080p")
        self.assertEqual(arc.quality_band(640, None), "480p")
        self.assertEqual(arc.quality_band(None, None), "480p")


class Mp4CandidateTests(unittest.TestCase):
    def test_format_field_is_ignored(self):
        files = [{"name": "Film.mp4", "format": "h.264", "size": "100"},
                 {"name": "Other.mp4", "format": "512Kb MPEG4", "size": "50"}]
        names = [c["name"] for c in arc._mp4_files(files)]
        self.assertEqual(names, ["Film.mp4", "Other.mp4"])

    def test_non_mp4_files_ignored(self):
        files = [{"name": "Film.mp4", "format": "MPEG4", "size": "100"},
                 {"name": "Film.mp3", "format": "MP3", "size": "10"},
                 {"name": "Film.txt", "format": "Text", "size": "1"}]
        self.assertEqual([c["name"] for c in arc._mp4_files(files)], ["Film.mp4"])

    def test_preview_trailer_sample_files_skipped(self):
        files = [{"name": "Film.mp4", "size": "100"},
                 {"name": "Film_preview.mp4", "size": "90"},
                 {"name": "Film-trailer.mp4", "size": "80"},
                 {"name": "sample.mp4", "size": "70"}]
        self.assertEqual([c["name"] for c in arc._mp4_files(files)], ["Film.mp4"])

    def test_512kb_sorts_last_and_plain_before_ia(self):
        files = [{"name": "Film_512kb.mp4", "size": "900"},
                 {"name": "Film.ia.mp4", "size": "800"},
                 {"name": "Film.mp4", "size": "700"}]
        names = [c["name"] for c in arc._mp4_files(files)]
        self.assertEqual(names, ["Film.mp4", "Film.ia.mp4", "Film_512kb.mp4"])

    def test_candidates_capped_at_three(self):
        files = [{"name": f"Film{i}.mp4", "size": str(100 - i)} for i in range(5)]
        self.assertEqual(len(arc._mp4_files(files)), 3)


class ProbeTests(unittest.TestCase):
    def test_range_206_video_passes(self):
        result = arc.probe_range("https://example.com/f.mp4",
                                 opener=lambda req, timeout: FakeResp(206, "video/mp4"))
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], 206)

    def test_range_200_fails_range_ignored(self):
        result = arc.probe_range("https://example.com/f.mp4",
                                 opener=lambda req, timeout: FakeResp(200, "video/mp4"))
        self.assertFalse(result["ok"])

    def test_range_404_fails(self):
        result = arc.probe_range("https://example.com/f.mp4",
                                 opener=lambda req, timeout: FakeResp(404, "text/html"))
        self.assertFalse(result["ok"])

    def test_range_wrong_content_type_fails(self):
        result = arc.probe_range("https://example.com/f.mp4",
                                 opener=lambda req, timeout: FakeResp(206, "text/html"))
        self.assertFalse(result["ok"])

    def test_range_transport_error_fails_not_raises(self):
        import urllib.error
        result = arc.probe_range(
            "https://example.com/f.mp4",
            opener=lambda req, timeout: (_ for _ in ()).throw(
                urllib.error.URLError("reset")))
        self.assertFalse(result["ok"])

    def test_ffprobe_video_plus_audio_plus_duration_passes(self):
        out = json.dumps({"streams": [
            {"codec_type": "video", "codec_name": "h264", "width": 640, "height": 480},
            {"codec_type": "audio", "codec_name": "aac"}],
            "format": {"duration": "1239.0"}})
        result = arc.probe_ffprobe("https://example.com/f.mp4",
                                   runner=lambda url: SimpleNamespace(
                                       returncode=0, stdout=out, stderr=""))
        self.assertEqual(result["width"], 640)
        self.assertEqual(result["duration"], 1239.0)
        self.assertTrue(result["has_audio"])

    def test_ffprobe_without_audio_fails(self):
        out = json.dumps({"streams": [
            {"codec_type": "video", "codec_name": "h264", "width": 640, "height": 480}],
            "format": {"duration": "100.0"}})
        result = arc.probe_ffprobe("https://example.com/f.mp4",
                                   runner=lambda url: SimpleNamespace(
                                       returncode=0, stdout=out, stderr=""))
        self.assertIsNone(result)

    def test_ffprobe_zero_duration_fails(self):
        out = json.dumps({"streams": [
            {"codec_type": "video", "codec_name": "h264", "width": 640, "height": 480},
            {"codec_type": "audio", "codec_name": "aac"}],
            "format": {"duration": "0"}})
        result = arc.probe_ffprobe("https://example.com/f.mp4",
                                   runner=lambda url: SimpleNamespace(
                                       returncode=0, stdout=out, stderr=""))
        self.assertIsNone(result)

    def test_ffprobe_missing_binary_fails_closed(self):
        result = arc.probe_ffprobe(
            "https://example.com/f.mp4",
            runner=lambda url: (_ for _ in ()).throw(FileNotFoundError("ffprobe")))
        self.assertIsNone(result)


class BuildRecordTests(unittest.TestCase):
    def test_golfers_end_to_end(self):
        record, reason = arc.build_record(
            "TheGolfers", golf_meta(), golf_files(),
            range_probe=range_ok, ffprobe_probe=ffprobe_width(640))
        self.assertEqual(reason, "")
        self.assertIsNotNone(record)
        self.assertEqual(record["canonical_key"], "archive_org:TheGolfers")
        self.assertEqual(record["clean_title"], "The Golfers")
        self.assertEqual(record["year"], 1929)
        self.assertEqual(record["source_site"], "archive.org")
        self.assertEqual(record["url"], "https://archive.org/details/TheGolfers")
        self.assertEqual(record["tmdb_id"], None)
        self.assertEqual(record["is_18_plus"], 0)
        self.assertEqual(record["poster_url"],
                         "https://archive.org/download/TheGolfers/__ia_thumb.jpg")
        self.assertEqual(len(record["releases"]), 1)
        rel = record["releases"][0]
        self.assertEqual(rel["quality"], "480p")
        self.assertEqual(rel["resolution"], "640x480")
        src = rel["sources"][0]
        self.assertEqual(src["service"], "archive_org")
        self.assertEqual(src["final_url"],
                         "https://archive.org/download/TheGolfers/The%20Golfers.mp4")
        self.assertEqual(src["playback_type"], "direct")
        self.assertEqual(src["status"], "active")
        self.assertEqual(src["is_temporary"], 0)
        self.assertEqual(record["raw_meta"]["license_kind"], "pd_mark")
        self.assertEqual(record["raw_meta"]["licenseurl"], PD_MARK)
        self.assertEqual(len(record["raw_meta"]["probe"]), 1)
        self.assertEqual(record["raw_meta"]["probe"][0]["range_status"], 206)

    def test_things_to_come_has_main_plus_512kb_releases(self):
        files = [{"name": "ThingsToComePresentedByMoviePowder.mp4", "format": "h.264",
                  "size": "579125328"},
                 {"name": "ThingsToComePresentedByMoviePowder_512kb.mp4",
                  "format": "512Kb MPEG4", "size": "404090179"}]
        widths = {"ThingsToComePresentedByMoviePowder.mp4": 1280,
                  "ThingsToComePresentedByMoviePowder_512kb.mp4": 480}

        def probe(url):
            name = url.rsplit("/", 1)[-1]
            import urllib.parse
            name = urllib.parse.unquote(name)
            return {"width": widths[name], "height": 720 if widths[name] >= 1280 else 360,
                    "codec": "h264", "duration": 5571.0, "has_audio": True}

        record, reason = arc.build_record(
            "ThingsToCome_835",
            {"title": "Things To Come", "year": 1936, "licenseurl": PD_OLD},
            files, range_probe=range_ok, ffprobe_probe=probe)
        self.assertEqual(reason, "")
        # Main file is 1280x720: 720p by height (a width rule would have
        # mislabelled it 1080p). The _512kb file is 480x360: 480p.
        self.assertEqual([r["quality"] for r in record["releases"]],
                         ["720p", "480p"])

    def test_sita_three_variants_land_in_three_bands(self):
        # Measured live 2026-11-09: Sita ships 1920x1080, 1280x720 and
        # 848x480 files. Height bands them 1080p / 720p / 480p — three
        # distinct bands, none gated by mistake.
        files = [{"name": "Sita_Sings_the_Blues_1080p.mp4", "size": "900"},
                 {"name": "Sita_Sings_the_Blues_720p.mp4", "size": "500"},
                 {"name": "Sita_Sings_the_Blues_480p_2150kbps.mp4", "size": "300"}]

        def probe(url):
            name = url.rsplit("/", 1)[-1]
            import urllib.parse
            name = urllib.parse.unquote(name)
            dims = {"Sita_Sings_the_Blues_1080p.mp4": (1920, 1080),
                    "Sita_Sings_the_Blues_720p.mp4": (1280, 720),
                    "Sita_Sings_the_Blues_480p_2150kbps.mp4": (848, 480)}[name]
            return {"width": dims[0], "height": dims[1], "codec": "h264",
                    "duration": 4920.0, "has_audio": True}

        record, reason = arc.build_record(
            "Sita_Sings_the_Blues",
            {"title": "Sita Sings the Blues", "year": 2008,
             "licenseurl": "https://creativecommons.org/publicdomain/zero/1.0/"},
            files, range_probe=range_ok, ffprobe_probe=probe)
        self.assertEqual(reason, "")
        self.assertEqual([r["quality"] for r in record["releases"]],
                         ["1080p", "720p", "480p"])

    def test_bowery_huge_ia_mp4_dropped_when_plain_is_hd(self):
        files = [{"name": "Bowery at Midnight (1942).ia.mp4", "format": "h.264 IA",
                  "size": "1270138207"},
                 {"name": "Bowery at Midnight (1942).mp4", "format": "MPEG4",
                  "size": "1270138207"}]
        record, reason = arc.build_record(
            "bowery-at-midnight-1942",
            {"title": "Bowery at Midnight (1942)", "year": 1942,
             "licenseurl": PD_MARK_HTTPS},
            files, range_probe=range_ok, ffprobe_probe=ffprobe_width(1556, 1080))
        self.assertEqual(reason, "")
        self.assertEqual(len(record["releases"]), 1)
        self.assertEqual(record["releases"][0]["sources"][0]["final_url"],
                         "https://archive.org/download/bowery-at-midnight-1942/"
                         "Bowery%20at%20Midnight%20%281942%29.mp4")

    def test_bowery_ia_mp4_kept_when_plain_is_not_hd(self):
        files = [{"name": "Bowery at Midnight (1942).ia.mp4", "format": "h.264 IA",
                  "size": "1270138207"},
                 {"name": "Bowery at Midnight (1942).mp4", "format": "MPEG4",
                  "size": "1270138207"}]
        record, reason = arc.build_record(
            "bowery-at-midnight-1942",
            {"title": "Bowery at Midnight (1942)", "year": 1942,
             "licenseurl": PD_MARK_HTTPS},
            files, range_probe=range_ok, ffprobe_probe=ffprobe_width(640, 480))
        self.assertEqual(reason, "")
        self.assertEqual(len(record["releases"]), 2)

    def test_karate_by_nc_skipped_despite_playing(self):
        record, reason = arc.build_record(
            "karate-warriors-sonny-chiba-kazuhiko-yamaguchi-1976",
            {"title": "Karate Warriors", "year": None, "licenseurl": CC_BY_NC},
            [{"name": "Karate Warriors 1976.mp4", "format": "MPEG4", "size": "471350673"}],
            range_probe=range_ok, ffprobe_probe=ffprobe_width(640, 288))
        self.assertIsNone(record)
        self.assertEqual(reason, "license_not_allowed")

    def test_dark_item_skipped(self):
        record, reason = arc.build_record(
            "night_of_the_living_dead",
            {"title": "Night of the Living Dead", "year": 1968,
             "licenseurl": PD_MARK, "is_dark": True},
            [{"name": "night.mp4", "format": "MPEG4", "size": "100"}],
            range_probe=range_ok, ffprobe_probe=ffprobe_width(640))
        self.assertIsNone(record)
        self.assertEqual(reason, "dark")

    def test_no_mp4_skipped(self):
        record, reason = arc.build_record(
            "some-item", {"title": "Some Film", "licenseurl": PD_MARK},
            [{"name": "film.mp3", "format": "MP3", "size": "10"}],
            range_probe=range_ok, ffprobe_probe=ffprobe_width(640))
        self.assertIsNone(record)
        self.assertEqual(reason, "no_mp4")

    def test_probe_failure_skips(self):
        record, reason = arc.build_record(
            "TheGolfers", golf_meta(), golf_files(),
            range_probe=range_fail, ffprobe_probe=ffprobe_width(640))
        self.assertIsNone(record)
        self.assertEqual(reason, "probe_failed")

    def test_ffprobe_missing_skips_never_imports_unproven(self):
        record, reason = arc.build_record(
            "TheGolfers", golf_meta(), golf_files(),
            range_probe=range_ok, ffprobe_probe=ffprobe_none)
        self.assertIsNone(record)
        self.assertEqual(reason, "probe_failed")

    def test_blondeinbondage_flagged_for_review(self):
        record, reason = arc.build_record(
            "blondeinbondage",
            {"title": "blondeinbondage", "year": 1957, "licenseurl": PD_MARK},
            [{"name": "Blonde_in_Bondage_1957_Movie.mp4", "format": "MPEG4",
              "size": "289871155"}],
            range_probe=range_ok, ffprobe_probe=ffprobe_width(472, 360))
        self.assertEqual(reason, "")
        self.assertEqual(record["is_18_plus"], 1)
        self.assertEqual(record["raw_meta"]["flag_reason"], "bondage")

    def test_bogard_year_from_identifier(self):
        record, reason = arc.build_record(
            "bogard-1975",
            {"title": "Bogard (1975)", "year": None, "licenseurl": PD_MARK},
            [{"name": "Bogard (1975).mp4", "format": "MPEG4", "size": "587142620"}],
            range_probe=range_ok, ffprobe_probe=ffprobe_width(416, 320))
        self.assertEqual(reason, "")
        self.assertEqual(record["year"], 1975)


class ExportStagingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "archive_org.db"

    def tearDown(self):
        self.tmp.cleanup()

    def _record(self):
        record, reason = arc.build_record(
            "TheGolfers", golf_meta(), golf_files(),
            range_probe=range_ok, ffprobe_probe=ffprobe_width(640))
        self.assertEqual(reason, "")
        return record

    def test_write_and_counts(self):
        totals = arc.export_staging(self.db, [self._record()])
        self.assertEqual(totals, {"posts_written": 1, "releases_written": 1,
                                  "sources_written": 1, "skipped": 0})
        conn = sqlite3.connect(self.db)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0], 1)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0], 1)
        row = conn.execute(
            "SELECT service, final_url, playback_type, status FROM sources"
            ).fetchone()
        self.assertEqual(row[0], "archive_org")
        self.assertTrue(row[1].startswith("https://archive.org/download/TheGolfers/"))
        self.assertEqual(row[2], "direct")
        self.assertEqual(row[3], "active")
        conn.close()

    def test_reexport_replaces_releases(self):
        arc.export_staging(self.db, [self._record()])
        record = self._record()
        record["releases"] = record["releases"] * 2
        arc.export_staging(self.db, [record])
        conn = sqlite3.connect(self.db)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0], 1)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM releases").fetchone()[0], 2)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0], 2)
        conn.close()

    def test_verify_ok_and_failing(self):
        arc.export_staging(self.db, [self._record()])
        ok, result = arc.verify_db(self.db)
        self.assertTrue(ok)
        self.assertEqual(result["posts"], 1)
        self.assertEqual(result["license_kinds"], {"pd_mark": 1})
        conn = sqlite3.connect(self.db)
        conn.execute(
            "INSERT INTO posts (canonical_key, title, clean_title, url)"
            " VALUES ('archive_org:bare', 'Bare', 'Bare',"
            " 'https://archive.org/details/bare')")
        conn.commit()
        conn.close()
        ok, result = arc.verify_db(self.db)
        self.assertFalse(ok)
        self.assertEqual(result["posts_without_release"], 1)


class HarvestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "archive_org.db"

    def tearDown(self):
        self.tmp.cleanup()

    def _fetch_json(self, docs, metas):
        def fetch(url):
            if "advancedsearch" in url:
                return {"response": {"numFound": len(docs), "docs": docs}}
            ident = url.rsplit("/", 1)[-1]
            return metas[ident]
        return fetch

    def test_harvest_writes_posts_and_counts_skips(self):
        docs = [{"identifier": "TheGolfers"},
                {"identifier": "karate-warriors"},
                {"identifier": "night_of_the_living_dead"}]
        metas = {
            "TheGolfers": {"metadata": golf_meta(), "files": golf_files()},
            "karate-warriors": {"metadata": {"title": "Karate Warriors",
                                             "licenseurl": CC_BY_NC},
                                "files": [{"name": "k.mp4", "size": "10"}]},
            "night_of_the_living_dead": {
                "metadata": {"title": "Night of the Living Dead",
                             "licenseurl": PD_MARK, "is_dark": True},
                "files": [{"name": "n.mp4", "size": "10"}]},
        }
        totals = arc.harvest(self.db, limit=10, fetch_json=self._fetch_json(docs, metas),
                             range_probe=range_ok,
                             ffprobe_probe=ffprobe_width(640), verbose=False)
        self.assertEqual(totals["posts"], 1)
        self.assertEqual(totals["skipped_license"], 1)
        self.assertEqual(totals["skipped_dark"], 1)
        self.assertEqual(totals["errors"], 0)
        ok, result = arc.verify_db(self.db)
        self.assertTrue(ok)

    def test_harvest_stops_at_limit(self):
        docs = [{"identifier": f"film-{i}"} for i in range(5)]
        metas = {f"film-{i}": {"metadata": {"title": f"Film {i}",
                                            "licenseurl": PD_MARK},
                               "files": [{"name": f"f{i}.mp4", "size": "10"}]}
                 for i in range(5)}
        totals = arc.harvest(self.db, limit=2, fetch_json=self._fetch_json(docs, metas),
                             range_probe=range_ok,
                             ffprobe_probe=ffprobe_width(640), verbose=False)
        self.assertEqual(totals["posts"], 2)
        self.assertEqual(totals["items"], 2)

    def test_duplicate_identifier_and_title_year_skipped(self):
        docs = [{"identifier": "film-a"}, {"identifier": "film-a"},
                {"identifier": "film-b"}]
        metas = {
            "film-a": {"metadata": {"title": "Same Film", "year": 1950,
                                    "licenseurl": PD_MARK},
                       "files": [{"name": "a.mp4", "size": "10"}]},
            "film-b": {"metadata": {"title": "Same Film", "year": 1950,
                                    "licenseurl": PD_MARK},
                       "files": [{"name": "b.mp4", "size": "10"}]},
        }
        totals = arc.harvest(self.db, limit=10, fetch_json=self._fetch_json(docs, metas),
                             range_probe=range_ok,
                             ffprobe_probe=ffprobe_width(640), verbose=False)
        self.assertEqual(totals["posts"], 1)
        self.assertEqual(totals["duplicates"], 1)
        self.assertEqual(totals["dup_title_year"], 1)


class CliTests(unittest.TestCase):
    def test_harvest_args_parse(self):
        args = arc.parse_args(["harvest", "--db", "/tmp/x.db", "--limit", "20",
                               "--start-page", "2"])
        self.assertEqual((args.command, args.db, args.limit, args.start_page),
                         ("harvest", "/tmp/x.db", 20, 2))

    def test_verify_and_stats_args_parse(self):
        self.assertEqual(arc.parse_args(["verify", "--db", "/tmp/x.db"]).command,
                         "verify")
        self.assertEqual(arc.parse_args(["stats"]).command, "stats")


if __name__ == "__main__":
    print("fixture: %s (offline — no network, no catalog)" % Path(__file__).name)
    unittest.main(verbosity=2)
