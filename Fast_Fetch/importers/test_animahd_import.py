#!/usr/bin/env python3
"""
test_animahd_import.py — offline unit tests for the AnimaHD staging importer.

No test here reaches the network and no test writes a database: the suite
exercises the pure readers (`decode_sec_route`, `player_url`, `parse_rows`,
`build_record`, `sources_for`) against fixtures shaped from the live page the
importer's own docstring recorded on 2026-10-28, plus the one staging guardrail
that matters. `socket.socket` is replaced with a raiser for the whole module so
an accidental live request fails the run instead of passing it.

The rule this suite exists to keep — the same rule `host_resolvers.py` and every
sibling importer test keep — is that a durable identifier may be stored and a
play-time result may never be. A row is written with the site's own unsigned
`/player/?file_id=` URL and the durable Google Drive file id; the secure-page
host and the `workers.dev?token=` byte URL are minted per play by
`unwrap_animahd` and must not appear anywhere in the record the importer builds.
"""

from __future__ import annotations

import base64
import contextlib
import io
import json
import re
import socket
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import import_animahd as ah  # noqa: E402


class _NoLiveSocket:
    def __init__(self, *args, **kwargs):
        raise AssertionError("offline suite attempted a live connection")


socket.socket = _NoLiveSocket  # type: ignore[attr-defined]


@contextlib.contextmanager
def silenced():
    buf = io.StringIO()
    with contextlib.ExitStack() as stack:
        for stream in ("stdout", "stderr"):
            stack.enter_context(mock.patch.object(sys, stream, buf))
        yield buf


AH_FILE_ID = "10i-vf0OzJqDkR0-a7MpPWKI0qERYAOp1"
PLAYER = f"https://animahd.com/player/?file_id={AH_FILE_ID}&show_id=194&ep=0"


def sec_route_href(player_url: str = PLAYER) -> str:
    """The `?sec_route=1&p=<base64>&s=<hmac>` envelope the site wraps links in."""
    blob = base64.b64encode(player_url.encode()).decode()
    return ("https://animahd.com/?sec_route=1&#038;p=" + blob + "&#038;s=8b5a1f63cafe")


def row_html(href: str | None = None, file_id: str = AH_FILE_ID) -> str:
    href = sec_route_href() if href is None else href
    return (
        "<a href='%s' class='app-ep-row-item' data-season='Season 1' style='x'>\n"
        "  <div class='ep-duration-badge'>23:12</div>\n"
        "  <div class='gdrive-ep-meta' data-fileid='%s'>\n"
        "    <div>[ANIMAHD.COM] S01E01 Naruto Shippuden.mkv</div>\n"
        "    <div>1080p HD &nbsp;&bull;&nbsp; Size: <span class='ep-size'>241.43 MB</span></div>\n"
        "  </div></a>" % (href, file_id)
    )


HEADER = """<h1 class="ff-title">Naruto Shippuden</h1>
<div class="ff-meta">2002 - 2017 &bull; 8.7 &bull; 298 Episodes &bull; 24 min per ep</div>
<div class="ff-synopsis">A ninja comes of age in a hidden village.</div>
<div class="ff-poster-wrap"><img src="https://animahd.com/p.jpg"></div>
<div class="ff-hero-bg" style="background-image: url('https://animahd.com/bg.avif')"></div>
<span class="ff-pill">Action</span><span class="ff-pill">Adventure</span>
"""


def wp_post(**over) -> dict:
    record = {
        "id": 194,
        "slug": "naruto-shippuden",
        "link": "https://animahd.com/naruto-shippuden/",
        "title": {"rendered": "[ANIMAHD] Naruto Shippuden [Hindi-Tamil-Tel-Mal-Ben-Eng-Jap] (2002)"},
        "date": "2026-01-01T00:00:00",
        "modified": "2026-01-01T00:00:00",
        "_mal_cached_year": "2002-2017",
        "_mal_cached_score": "8.7",
        "_mal_cached_genres": "Action, Adventure",
        "_mal_cached_thumb": "/thumb.jpg",
        "_mal_cached_season": "TV",
        "_animesuki_lang_badge": "Multi",
        "_embedded": {"wp:term": [
            [{"name": "Action", "taxonomy": "category"}, {"name": "Ecchi", "taxonomy": "category"}],
            [{"name": "Ongoing", "taxonomy": "post_tag"}],
        ]},
    }
    record.update(over)
    return record


# ---------------------------------------------------------------------------
# The signed envelope and the durable URL it hides
# ---------------------------------------------------------------------------

class TestSecRoute(unittest.TestCase):
    def test_the_base64_envelope_decodes_to_the_real_link(self):
        self.assertEqual(ah.decode_sec_route(sec_route_href()), PLAYER)

    def test_a_plain_link_is_not_an_envelope(self):
        self.assertEqual(ah.decode_sec_route("https://animahd.com/naruto-shippuden/"), "")

    def test_garbage_in_the_envelope_is_reported_not_raised(self):
        self.assertEqual(ah.decode_sec_route("https://x.test/?sec_route=1&p=@@@not-b64@@@&s=z"), "")

    def test_the_player_url_is_the_durable_unsigned_watch_link(self):
        self.assertEqual(ah.player_url(sec_route_href()), PLAYER)

    def test_a_decoded_link_that_is_not_the_player_page_is_not_a_player_url(self):
        href = sec_route_href("https://animahd.com/naruto-shippuden/")
        self.assertEqual(ah.player_url(href), "")

    def test_a_foreign_host_inside_the_envelope_is_not_a_player_url(self):
        href = sec_route_href("https://evil.test/player/?file_id=" + AH_FILE_ID)
        self.assertEqual(ah.player_url(href), "")

    def test_the_gdrive_id_is_validated_before_anything_uses_it(self):
        # The player URL carries the same `file_id` the row published, so it is a
        # valid Drive id read; anything outside the character class is rejected.
        self.assertEqual(ah.gdrive_file_id(PLAYER), AH_FILE_ID)
        self.assertEqual(ah.gdrive_file_id(f"https://animahd.com/x?file_id={AH_FILE_ID}"),
                         AH_FILE_ID)
        self.assertEqual(ah.gdrive_file_id(f"https://drive.google.com/file/d/{AH_FILE_ID}/view"),
                         AH_FILE_ID)
        self.assertEqual(ah.gdrive_file_id("https://animahd.com/x?file_id=short"), "")
        self.assertEqual(ah.gdrive_file_id("https://animahd.com/x?file_id=bad*chars*here*123456"), "")


# ---------------------------------------------------------------------------
# Parsing the page
# ---------------------------------------------------------------------------

class TestRowParsing(unittest.TestCase):
    def test_one_published_row_yields_its_durable_fields(self):
        rows = ah.parse_rows(row_html())
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["file_id"], AH_FILE_ID)
        self.assertEqual(row["season"], 1)
        self.assertEqual(row["episode"], 1)
        self.assertEqual(row["season_label"], "Season 1")
        self.assertEqual(row["container"], "mkv")
        self.assertEqual(row["quality"], "1080p HD")
        self.assertEqual(row["duration"], "23:12")
        self.assertEqual(row["duration_seconds"], 1392)
        self.assertEqual(row["size_bytes"], round(241.43 * 1024 * 1024))
        self.assertEqual(row["player_url"], PLAYER)
        self.assertEqual(row["subtitle_present"], 0)
        self.assertFalse(row["is_new"])

    def test_a_page_with_no_rows_is_not_an_error(self):
        self.assertEqual(ah.parse_rows("<html><body>nothing here</body></html>"), [])
        self.assertEqual(ah.parse_rows(""), [])

    def test_the_file_id_falls_back_to_the_decoded_envelope(self):
        # A row that omits data-fileid is still resolvable via p= -> /player/?file_id=.
        html = row_html().replace(f" data-fileid='{AH_FILE_ID}'", "")
        self.assertEqual(ah.parse_rows(html)[0]["file_id"], AH_FILE_ID)


class TestEpisodeName(unittest.TestCase):
    def test_the_two_observed_watermarks_are_stripped_but_the_raw_kept(self):
        for brand in ("[ANIMAHD.COM]", "[ANIMAHD]"):
            parsed = ah.parse_episode_name(f"{brand} S03E54 Naruto Shippuden.mkv")
            self.assertEqual(parsed["brand"], brand)
            self.assertEqual(parsed["season"], 3)
            self.assertEqual(parsed["episode"], 54)
            self.assertEqual(parsed["file_title"], "S03E54 Naruto Shippuden")
            self.assertEqual(parsed["container"], "mkv")
            self.assertIn(brand, parsed["raw_name"])

    def test_an_unrecognised_shape_keeps_the_raw_and_names_nothing(self):
        parsed = ah.parse_episode_name("Some Odd File")
        self.assertEqual(parsed["raw_name"], "Some Odd File")
        self.assertIsNone(parsed["season"])
        self.assertEqual(parsed["container"], "")

    def test_empty_name_is_not_a_crash(self):
        self.assertEqual(ah.parse_episode_name("")["file_title"], "")
        self.assertEqual(ah.parse_episode_name(None)["raw_name"], "")


class TestHeader(unittest.TestCase):
    def test_the_ff_block_publishes_work_metadata(self):
        header = ah.parse_header(HEADER)
        self.assertEqual(header["page_title"], "Naruto Shippuden")
        self.assertEqual(header["year"], 2002)
        self.assertEqual(header["episode_claim"], "298 Episodes")
        self.assertEqual(header["synopsis"], "A ninja comes of age in a hidden village.")
        self.assertEqual(header["poster_url"], "https://animahd.com/p.jpg")
        self.assertEqual(header["backdrop_url"], "https://animahd.com/bg.avif")
        self.assertIn("Action", header["genres"])

    def test_seo_boilerplate_synopsis_is_not_recorded_as_plot(self):
        page = HEADER.replace(
            "A ninja comes of age in a hidden village.",
            "stream naruto full episodes in hd audio video layout")
        self.assertEqual(ah.parse_header(page)["synopsis"], "")


# ---------------------------------------------------------------------------
# Classification decisions an auditor asks about
# ---------------------------------------------------------------------------

class TestClassification(unittest.TestCase):
    def test_adult_is_flagged_only_on_explicit_tokens(self):
        self.assertEqual(ah.looks_adult("Some Hentai Special"), 1)
        self.assertEqual(ah.looks_adult("Naruto Shippuden"), 0)

    def test_genre_markers_are_preserved_but_not_flagged(self):
        self.assertEqual(ah.looks_adult("Ecchi", "Girls Love"), 0)
        self.assertEqual(ah.maturity_tags(["Ecchi"], ["Girls Love"]), ["Ecchi", "Girls Love"])

    def test_the_work_year_beats_the_publish_date(self):
        year, source = ah.year_from(wp_post(), {})
        self.assertEqual(year, 2002)
        self.assertIn("range", source)

    def test_a_missing_cached_year_falls_back_to_the_title_parenthetical(self):
        year, source = ah.year_from({"_mal_cached_year": "",
                                     "title": {"rendered": "Foo (2019)"}}, {})
        self.assertEqual((year, source), (2019, "title parenthetical"))

    def test_no_published_year_is_null_not_a_guess(self):
        self.assertEqual(ah.year_from({"_mal_cached_year": "", "title": {"rendered": "Foo"}}, {}),
                         (None, "none published"))

    def test_the_audio_bracket_becomes_a_language_list(self):
        langs = ah.languages_from_title(
            "[ANIMAHD] Naruto [Hindi-Tamil-Tel-Mal-Ben-Eng-Jap]")
        self.assertEqual(langs, ["Hindi", "Tamil", "Telugu", "Malayalam",
                                 "Bengali", "English", "Japanese"])


# ---------------------------------------------------------------------------
# The invariant the whole importer exists to keep
# ---------------------------------------------------------------------------

class TestNoPlayTimeUrlIsStored(unittest.TestCase):
    def test_sources_are_the_durable_download_and_watch_rows_only(self):
        sources = ah.sources_for({"file_id": AH_FILE_ID, "player_url": PLAYER}, "Naruto")
        self.assertEqual([s["playback_type"] for s in sources], ["download", "url"])
        self.assertEqual([s["service"] for s in sources],
                         [ah.SERVICE_GDRIVE, ah.SERVICE_PLAYER])
        download, watch = sources
        self.assertEqual(download["resource_id"], AH_FILE_ID)
        self.assertEqual(download["is_temporary"], 0)
        self.assertTrue(download["final_url"].startswith("https://drive.google.com/uc"))
        self.assertEqual(watch["source_url"], PLAYER)
        self.assertEqual(watch["is_temporary"], 1)

    def test_an_episode_with_only_one_durable_reference_gets_one_row(self):
        self.assertEqual(len(ah.sources_for({"file_id": AH_FILE_ID}, "X")), 1)
        self.assertEqual(len(ah.sources_for({"player_url": PLAYER}, "X")), 1)
        self.assertEqual(ah.sources_for({}, "X"), [])

    def test_a_full_record_never_carries_a_signed_or_play_time_url(self):
        page = HEADER + row_html()
        record = ah.build_record(wp_post(), page, "https://animahd.com/naruto-shippuden/")
        blob = json.dumps(record)
        # The per-load byte endpoint, the per-file secure host and the token must
        # never reach the ledger — only the durable player URL and the file id.
        for forbidden in ("workers.dev", "token=", "eid=", "animahd.fun", ".m3u8"):
            self.assertNotIn(forbidden, blob, f"play-time data leaked: {forbidden}")
        # And the durable identifiers are exactly where they should be.
        self.assertEqual(record["releases"][0]["bridge_url"], PLAYER)
        stored_urls = [s["source_url"] for r in record["releases"] for s in r["sources"]]
        self.assertTrue(all(ah._allowed_source_url(u) for u in stored_urls), stored_urls)

    def test_record_shape_is_a_series_with_two_durables_per_episode(self):
        record = ah.build_record(wp_post(), HEADER + row_html(),
                                 "https://animahd.com/naruto-shippuden/")
        self.assertEqual(record["media_type"], "series")
        self.assertEqual(record["is_18_plus"], 0)
        self.assertEqual(record["is_animated"], 1)
        self.assertEqual(record["clean_title"], "Naruto Shippuden")
        self.assertEqual(record["year"], 2002)
        self.assertEqual(len(record["releases"]), 1)
        self.assertEqual(len(record["releases"][0]["sources"]), 2)


# ---------------------------------------------------------------------------
# Staging isolation
# ---------------------------------------------------------------------------

class TestStagingIsolation(unittest.TestCase):
    def test_the_default_database_is_the_staging_file_not_production(self):
        db = str(ah.DEFAULT_DB_PATH)
        self.assertEqual(db, "/home/ubuntu/radd-stream-data/animahd.db")
        self.assertNotIn("fast_fetch.db", db)

    def test_the_build_parser_advertises_the_staging_target(self):
        parser = ah._build_parser()
        self.assertIn("animahd.db", parser.description)


if __name__ == "__main__":
    unittest.main(verbosity=2)
