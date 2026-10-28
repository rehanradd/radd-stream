#!/usr/bin/env python3
"""
test_animahd_import.py — offline unit tests for the AnimaHD staging importer.

No test here reaches the network: the suite exercises the pure readers
(`decode_sec_route`, `player_url`, `parse_rows`, `build_record`, `sources_for`)
against fixtures shaped from the live page the importer's own docstring recorded
on 2026-10-28, plus the staging guardrails that matter. `socket.socket` is
replaced with a raiser for the whole module so an accidental live request fails
the run instead of passing it. The grading tests do write a database — always a
file under `tempfile.mkdtemp()`, removed in `tearDown`, and never a path any
crawler reads.

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
import shutil
import socket
import sqlite3
import sys
import tempfile
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

# Measured 2026-10-28 on the saved /tmp/animahd_naruto.html: 27 rows
# (S16E349..S16E375) publish `r2reid:<long base64>` as their data-fileid — a
# different id scheme whose colon is outside the Drive id class. The bug this
# guards: those rows interpolated the unvalidated attribute into
# drive.google.com/uc?...&id=r2reid:…, inventing 27 download sources.
R2_PREFIX = "r2reid:" + "NGE1MDVmNTg1YzUwNTk1NTRjMzE0MjIwMjczMTVmNzA2MzY0NjU3" + "ZTMx"
R2_PLAYER = f"https://animahd.com/player/?file_id={R2_PREFIX}&show_id=194&ep=349"


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

    def test_the_plus_token_is_found_in_every_shape_the_site_writes_it(self):
        for label in ("Foo 18+ Cut", "Foo (18+)", "Foo 18 + HD", "Foo 18+"):
            self.assertEqual(ah.looks_adult(label), 1, label)
        self.assertEqual(ah.looks_adult("Episode 18 of 24"), 0)

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
# The adult flag is a decision, not a field that a later crawl can undo
# ---------------------------------------------------------------------------

def _flag_of(db_path, key: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute("SELECT is_18_plus FROM posts WHERE canonical_key = ?",
                            (key,)).fetchone()[0]
    finally:
        conn.close()


class TestAdultFlagSticky(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="animahd_flag_")
        self.db = Path(self.dir) / "animahd.db"
        self.record = ah.build_record(
            wp_post(), HEADER + row_html(), "https://animahd.com/naruto-shippuden/")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_a_reexport_with_a_zero_does_not_clear_the_adult_flag(self):
        """MAX() is the sticky rule; a COALESCE over it would un-flag the series."""
        graded = dict(self.record, is_18_plus=1)
        ah.export_staging(self.db, [graded])
        self.assertEqual(_flag_of(self.db, graded["canonical_key"]), 1)
        ah.export_staging(self.db, [dict(graded, is_18_plus=0)])
        self.assertEqual(_flag_of(self.db, graded["canonical_key"]), 1,
                         "a re-export cleared an adult flag that was already set")

    def test_a_series_first_seen_clean_still_becomes_adult(self):
        """Sticky means never going backwards, not never going forwards."""
        clean = dict(self.record, is_18_plus=0)
        ah.export_staging(self.db, [clean])
        self.assertEqual(_flag_of(self.db, clean["canonical_key"]), 0)
        ah.export_staging(self.db, [dict(clean, is_18_plus=1)])
        self.assertEqual(_flag_of(self.db, clean["canonical_key"]), 1)

    def test_is_animated_follows_the_same_rule(self):
        graded = dict(self.record, is_animated=1)
        ah.export_staging(self.db, [graded])
        ah.export_staging(self.db, [dict(graded, is_animated=0)])
        conn = sqlite3.connect(self.db)
        try:
            stored = conn.execute("SELECT is_animated FROM posts WHERE canonical_key = ?",
                                  (graded["canonical_key"],)).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(stored, 1)

    def test_no_importer_puts_the_grade_columns_back_through_coalesce(self):
        """Fleet guard: the exclusion tuple must name both flags, in every importer."""
        here = Path(__file__).resolve().parent
        offenders = []
        checked = 0
        for module in sorted(here.glob("import_*.py")):
            source = module.read_text(encoding="utf-8")
            for match in re.finditer(r"if c not in \(([^)]*)\)", source):
                names = match.group(1)
                if "canonical_key" not in names:
                    continue
                checked += 1
                if "is_18_plus" not in names or "is_animated" not in names:
                    offenders.append(module.name)
        self.assertGreaterEqual(checked, 8,
                                "the guard stopped finding the upsert it guards")
        self.assertEqual(offenders, [],
                         f"{offenders} let a re-export overwrite a graded flag")


# ---------------------------------------------------------------------------
# The queue payload the crawl later parses
# ---------------------------------------------------------------------------

def live_term(name: str, taxonomy: str) -> dict:
    """A term as the REST collection actually ships it: a dict, not a name."""
    return {"id": 16, "link": f"https://animahd.com/category/{name}/", "name": name,
            "slug": name.lower().replace(" ", "-"), "taxonomy": taxonomy,
            "yoast_head": "<title>Action Archives - A Universe Of Anime</title>",
            "_links": {"self": [{"href": "https://animahd.com/wp/v2/trees/16"}]}}


class TestQueuePayload(unittest.TestCase):
    def test_a_real_rest_record_survives_the_queue_projection(self):
        """The live `wp:term` is groups of term dicts; the projection must not walk into them."""
        post = wp_post(_embedded={"wp:term": [
            [live_term("Action", "category"), live_term("Adventure", "category")],
            [live_term("Ongoing", "post_tag")]]})
        payload = ah._queue_json(post)
        groups = payload["_embedded"]["wp:term"]
        self.assertEqual([[t["name"] for t in group] for group in groups],
                         [["Action", "Adventure"], ["Ongoing"]])
        self.assertEqual([t["taxonomy"] for group in groups for t in group],
                         ["category", "category", "post_tag"])

    def test_the_projected_payload_reads_back_as_the_full_record(self):
        """Nothing is lost between the queue and the crawl that reads it."""
        flat = ah.terms_from_embed(wp_post())
        self.assertEqual(ah.terms_from_embed(ah._queue_json(wp_post())), flat)
        self.assertEqual(flat, (["Action", "Ecchi"], ["Ongoing"]))

    def test_the_projection_keeps_the_cached_mal_fields(self):
        payload = ah._queue_json(wp_post())
        self.assertEqual(payload["_mal_cached_year"], "2002-2017")
        self.assertEqual(payload["_mal_cached_score"], "8.7")
        self.assertEqual(payload["link"], "https://animahd.com/naruto-shippuden/")

    def test_the_boilerplate_body_stays_out_of_the_queue(self):
        payload = ah._queue_json(wp_post(content={"rendered": "<p>" + "x" * 5000}))
        self.assertNotIn("content", payload)
        self.assertLess(len(json.dumps(payload)), 2000)

    def test_a_post_with_no_terms_projects_an_empty_group_list(self):
        payload = ah._queue_json({"id": 1, "link": "https://animahd.com/x/"})
        self.assertEqual(payload["_embedded"], {"wp:term": []})
        self.assertEqual(ah.terms_from_embed(payload), ([], []))


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


class TestRejectedFileId(unittest.TestCase):
    """The r2reid: rows: an unvalidated data-fileid must never become a Drive URL.

    Two shapes were measured on 2026-10-28 and both are pinned here: the
    attribute alone is bad while the envelope still carries a real id (recover it),
    and both bad (emit no download row, keep the watch row, record the reject).
    """

    def test_attribute_rejected_but_envelope_recovers_the_real_id(self):
        # data-fileid is r2reid:, but the href envelope decodes to a real player
        # URL whose file_id is a valid Drive id: fall back and accept that.
        rows = ah.parse_rows(row_html(sec_route_href(PLAYER), R2_PREFIX))
        row = rows[0]
        self.assertEqual(row["raw_file_id"], R2_PREFIX)     # audit keeps the reject
        self.assertEqual(row["file_id"], AH_FILE_ID)        # recovered from envelope
        self.assertNotIn("r2reid", row["file_id"])
        download = next(s for s in ah.sources_for(row, "Naruto")
                        if s["service"] == ah.SERVICE_GDRIVE)
        self.assertIn(AH_FILE_ID, download["source_url"])
        self.assertNotIn("r2reid", download["source_url"])

    def test_a_rejected_id_builds_no_drive_url_and_keeps_the_player_row(self):
        # Both the attribute and the envelope carry only the r2reid scheme: no
        # valid Drive id exists, so there is no download row — but the durable
        # site watch URL stays, so the episode is not unplayable.
        rows = ah.parse_rows(row_html(sec_route_href(R2_PLAYER), R2_PREFIX))
        row = rows[0]
        self.assertEqual(row["file_id"], "")
        self.assertEqual(row["raw_file_id"], R2_PREFIX)
        sources = ah.sources_for(row, "Naruto")
        self.assertEqual([s["service"] for s in sources], [ah.SERVICE_PLAYER])
        self.assertFalse(any(s["service"] == ah.SERVICE_GDRIVE for s in sources))
        self.assertEqual(sources[0]["source_url"], R2_PLAYER)

    def test_sources_for_refuses_an_unvalidated_id_even_if_a_row_forgets_to(self):
        # The URL-build boundary is the second gate: a bare r2reid file_id passed
        # straight in still produces no download row.
        sources = ah.sources_for({"file_id": R2_PREFIX, "player_url": R2_PLAYER}, "X")
        self.assertEqual([s["service"] for s in sources], [ah.SERVICE_PLAYER])

    def test_build_record_counts_rejects_and_never_interpolates_one(self):
        page = HEADER + row_html(sec_route_href(R2_PLAYER), R2_PREFIX)
        record = ah.build_record(wp_post(), page, "https://animahd.com/naruto-shippuden/")
        rejected = record["raw_meta"]["rejected_file_ids"]
        self.assertEqual(len(rejected), 1)
        self.assertTrue(rejected[0]["raw"].startswith("r2reid:"))
        for release in record["releases"]:
            for source in release["sources"]:
                self.assertNotIn("r2reid", source.get("source_url", "")
                                 if source["service"] == ah.SERVICE_GDRIVE else "")
        # No drive.google.com download row was invented for the rejected id.
        self.assertEqual([s["service"] for r in record["releases"] for s in r["sources"]],
                         [ah.SERVICE_PLAYER])


class TestFailureRetries(unittest.TestCase):
    """
    A requeued row must still run out of attempts, and must say why it failed.

    `/from-old-country-bumpkin-to-master-swordsman/` answers 200 with zero episode
    rows in the delivered HTML — its grid is built client-side — so it declines
    every pass. With the cap written after the requeue branch, `scraped = 2` was a
    queued state it could never leave: an uncapped retry, and no record anywhere of
    the reason.
    """

    LOC = "https://animahd.com/from-old-country-bumpkin-to-master-swordsman/"

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="animahd_q_")
        self.db = Path(self.dir) / "animahd.db"
        conn = sqlite3.connect(self.db)
        ah.ensure_schema(conn)
        conn.execute("INSERT INTO sitemap_cache (loc, slug, scraped, raw_json) "
                     "VALUES (?, ?, 0, ?);",
                     (self.LOC, "from-old-country-bumpkin-to-master-swordsman",
                      json.dumps(wp_post())))
        conn.commit()
        conn.close()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _row(self):
        conn = sqlite3.connect(self.db)
        try:
            return conn.execute("SELECT scraped, error_count, last_error "
                                "FROM sitemap_cache WHERE loc = ?",
                                (self.LOC,)).fetchone()
        finally:
            conn.close()

    def test_a_declined_page_is_retried_and_its_reason_is_stored(self):
        ah._bump_error(self.db, self.LOC, "no-episode-rows", requeue=True)
        scraped, errors, reason = self._row()
        self.assertEqual(errors, 1)
        self.assertEqual(reason, "no-episode-rows")
        self.assertIn(scraped, ah.QUEUED_SCRAPE_STATES)

    def test_requeue_cannot_outlive_the_three_attempt_cap(self):
        for _ in range(3):
            ah._bump_error(self.db, self.LOC, "no-episode-rows", requeue=True)
        scraped, errors, _ = self._row()
        self.assertEqual(errors, 3)
        self.assertEqual(scraped, -1)

    def test_a_row_moved_off_the_site_parks_on_its_first_404(self):
        ah._bump_error(self.db, self.LOC, "http-404", park_now=True)
        self.assertEqual(self._row(), (-1, 1, "http-404"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
