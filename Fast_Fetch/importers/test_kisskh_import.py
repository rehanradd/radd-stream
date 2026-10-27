#!/usr/bin/env python3
"""
test_kisskh_import.py — offline unit tests for the kisskh staging importer.

Everything here runs without a network: the two fetch seams sit on top of one
injectable call each (`_OPENER.open` / `_NO_REDIRECT_OPENER.open`), so the seam
bodies — the retry loop, the gate short-circuit, the redirect walk — are
exercised for real instead of being patched away. The fixtures are shaped from
live kisskh.asia payloads captured on 2026-10-27: the WP REST record, the
player-data blob, the eleven subtitle codes, and the `*` hidden-slot form.
"""

from __future__ import annotations

import contextlib
import io
import json
import signal
import socket
import sqlite3
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import import_kisskh as kk  # noqa: E402


class _NoLiveSocket:
    """
    Replaces socket.socket for the whole suite: a test that reaches the network
    is a bug, and it should say so in the failure list rather than hang until the
    CDN's rate limit answers.
    """

    def __init__(self, *args, **kwargs):
        raise AssertionError("offline suite attempted a live connection")


socket.socket = _NoLiveSocket


@contextlib.contextmanager
def silenced():
    """
    Capture what the importer prints instead of letting it join the suite's own
    progress line. A test that cares about the wording asserts on the buffer;
    a test that only needs the module to stay quiet discards it.
    """
    buf = io.StringIO()
    with contextlib.ExitStack() as stack:
        for stream in ("stdout", "stderr"):
            stack.enter_context(mock.patch.object(sys, stream, buf))
        yield buf

LANGS = "Filipino,Khmer,English,Indonesian,Malay,Portuguese,Arabic,Hindi,German,French,Spanish"
CODES = tuple(kk.SUBTITLE_LANGS)
SUB_ROOT = "https://sub.cdnauto.xyz/kr/Test%20Drama"


def track(ep: str, code: str) -> str:
    return f"{SUB_ROOT}/{ep}.{code}.vtt"


def slot(ep: str, video: str = "", codes=CODES, marker: str = "") -> str:
    """One episode of a jw group, in the site's own layout."""
    video = video or f"https://hlscdn.vip/media/file{ep}.mp4"
    subs = "\n".join(f"{track(ep, c)}," for c in codes)
    return f"{marker}{video}|{LANGS}|\n{subs}"


def blob(eps=("1", "2"), tail: str = '<img src="https://image.tmdb.org/t/p/w1000/p.jpg"/>') -> str:
    return ";".join(slot(e) for e in eps) + (";" + tail if tail else "")


def term_group(taxonomy: str, *names: str) -> list[dict]:
    return [{"taxonomy": taxonomy, "name": n, "id": 100 + i} for i, n in enumerate(names)]


def wp_record(pid=101, slug="test-drama", title="Test Drama", terms=(), content="",
              media="https://kisskh.asia/wp-content/uploads/2026/05/55.webp",
              link=None):
    terms = terms or (term_group("genre", "Romance", "Comedy")
                      + term_group("country", "Korean")
                      + term_group("actor", "An Yuxi")
                      + term_group("category", "Drama"))
    # _embedded["wp:term"] is a list of taxonomy groups; accept either the flat
    # or the grouped spelling and always store the grouped one, as the API does.
    groups = list(terms) if terms and isinstance(terms[0], list) else [list(terms)]
    return {
        "id": pid, "slug": slug, "link": link or f"{kk.BASE_URL}/{slug}/",
        "title": {"rendered": title}, "date": "2026-05-01T10:00:00",
        "modified": "2026-05-06T10:00:00",
        "content": {"rendered": content},
        "_embedded": {"wp:term": groups, "wp:featuredmedia": [{"source_url": media}]},
    }


class FakeResponse:
    """The narrow surface the seams actually touch."""

    def __init__(self, body="", status=200, url="https://kisskh.asia/x", headers=None):
        self._body = body.encode("utf-8") if isinstance(body, str) else body
        self.status = status
        self._url = url
        self.headers = headers

    def read(self) -> bytes:
        return self._body

    def geturl(self) -> str:
        return self._url


class UnreadableBody(io.BytesIO):
    """An error body the server closed before we could read it."""

    def read(self, *args):
        raise OSError("body was already closed")


def http_error(code: int, body="", headers=None, readable=True):
    fp = io.BytesIO(body.encode()) if readable else UnreadableBody()
    return urllib.error.HTTPError("https://kisskh.asia/x", code, "nope", headers or {}, fp)


class TestScrubAndSplit(unittest.TestCase):
    def test_invisible_characters_are_removed_before_anything_is_parsed(self):
        self.assertEqual(kk._scrub_invisible("a​b﻿c d"), "a b c d")
        self.assertEqual(kk._scrub_invisible(None), "")

    def test_comments_scripts_and_block_tags_leave_clean_lines(self):
        lines = kk.strip_html_to_lines(
            "<!-- {nextServer} --><script>var x=1;</script>one<br>two<p>three</p><b>4</b>")
        self.assertEqual(lines, ["one", "two", "three", "4"])
        self.assertEqual(kk.strip_html_to_lines(None), [])

    def test_brace_entities_are_rewritten_to_markers(self):
        out = kk.normalize_blob("&#123;nextServer&#125; a &lbrace;embed&rbrace; &#x7b;&#x7d;")
        self.assertIn("{nextServer}", out)
        self.assertIn("{embed}", out)
        self.assertNotIn("&#", out)

    def test_bare_misspelt_words_become_the_canonical_markers(self):
        out = kk.normalize_blob("one\nnextserver two; embed three")
        self.assertIn("{nextServer}", out)
        self.assertIn("{embed}", out)

    def test_doubled_and_loose_brace_spellings_collapse(self):
        out = kk.normalize_blob("a {{ nexServer }} b { embed } c")
        self.assertEqual(out, "a {nextServer} b {embed} c")

    def test_server_groups_split_and_empty_groups_are_dropped(self):
        groups = kk.split_server_groups(f"{slot('1')};{slot('2')}"
                                        f"{{nextServer}};;  {{nextServer}}{slot('3')}")
        self.assertEqual(len(groups), 2)
        self.assertTrue(all(g["type"] == "jw" for g in groups))
        self.assertEqual([len(kk.parse_jw_group(g["body"])) for g in groups], [2, 1])

    def test_the_embed_marker_forces_a_group_type(self):
        groups = kk.split_server_groups(
            "{embed}https://kisskh.asia/embed/a;https://kisskh.asia/embed/b"
            "{nextServer}{embed}https://hlscdn.vip/media/x.mp4|English|")
        self.assertEqual([g["type"] for g in groups], ["embed", "embed"])

    def test_the_trailing_image_is_a_poster_not_part_of_the_stream(self):
        poster, rest = kk.split_html_and_poster(blob(eps=("1",)))
        self.assertEqual(poster, "https://image.tmdb.org/t/p/w1000/p.jpg")
        self.assertNotIn("<img", rest)
        self.assertEqual(kk.split_html_and_poster("no image here"), ("", "no image here"))


class TestDetectType(unittest.TestCase):
    def test_a_pipe_header_means_direct_media(self):
        self.assertEqual(kk.detect_type(f"https://a.com/v.mp4|{LANGS}|"), "jw")

    def test_every_media_extension_counts_as_direct_media(self):
        for ext in ("vtt", "srt", "txt", "m3u8", "mp4", "mpd"):
            with self.subTest(ext=ext):
                self.assertEqual(kk.detect_type(f"https://cdn.example/x.{ext}?a=1"), "jw")

    def test_a_group_holding_nothing_media_shaped_is_embed(self):
        self.assertEqual(kk.detect_type("https://kisskh.asia/embed/abc"), "embed")

    def test_a_protocol_relative_url_is_made_absolute(self):
        self.assertEqual(kk._normalize_http_url("//cdn.example/a.mp4"),
                         "https://cdn.example/a.mp4")

    def test_non_http_and_unparsable_targets_are_refused(self):
        self.assertEqual(kk._normalize_http_url("ftp://cdn.example/a"), "")
        self.assertEqual(kk._normalize_http_url("https://"), "")
        self.assertEqual(kk._normalize_http_url("http://[bad-url"), "")
        self.assertEqual(kk._normalize_http_url(""), "")


class TestJWBlock(unittest.TestCase):
    def test_one_slot_holds_a_video_eleven_tracks_and_the_language_header(self):
        parsed = kk.parse_jw_block(slot("7"))
        self.assertEqual(parsed["episode"], 7)
        self.assertEqual(parsed["video"], "https://hlscdn.vip/media/file7.mp4")
        self.assertEqual(len(parsed["subtitles"]), 11)
        self.assertEqual(parsed["subtitles"]["English"], track("7", "en"))
        self.assertEqual(parsed["subtitle_languages"], list(kk.SUBTITLE_LANGS.values()))
        self.assertFalse(parsed["hidden"])

    def test_a_star_slot_is_published_but_not_playable(self):
        parsed = kk.parse_jw_block("*https://bigf.imostatic.com|" + LANGS + "|\n"
                                   + track("16", "en"))
        self.assertTrue(parsed["hidden"])
        self.assertEqual(parsed["video"], "https://bigf.imostatic.com")
        self.assertIsNone(parsed["scheduled"])

    def test_a_scheduled_slot_keeps_its_time(self):
        parsed = kk.parse_jw_block("${2026-11-01 20:00}" + slot("3"))
        self.assertEqual(parsed["scheduled"], "2026-11-01 20:00")
        self.assertEqual(parsed["episode"], 3)

    def test_a_bare_dollar_means_scheduled_without_a_time(self):
        parsed = kk.parse_jw_block("$" + slot("4"))
        self.assertEqual(parsed["scheduled"], "")

    def test_a_group_with_tracks_but_no_video_still_records_the_tracks(self):
        parsed = kk.parse_jw_block("|" + LANGS + "|\n" + track("9", "en"))
        self.assertEqual(parsed["video"], "")
        self.assertEqual(parsed["subtitles"], {"English": track("9", "en")})
        self.assertEqual(parsed["episode"], 9)

    def test_an_empty_or_junk_block_is_not_an_episode(self):
        self.assertIsNone(kk.parse_jw_block("   "))
        self.assertIsNone(kk.parse_jw_block("|,|not a url at all"))

    def test_trailing_commas_and_semicolons_are_not_part_of_a_url(self):
        parsed = kk.parse_jw_block(f"https://hlscdn.vip/media/x.mp4|{LANGS}|\n"
                                   f"{track('1', 'en')},, {track('1', 'hi')},;")
        self.assertEqual(parsed["subtitles"],
                         {"English": track("1", "en"), "Hindi": track("1", "hi")})

    def test_an_unlisted_language_code_keeps_its_own_name(self):
        parsed = kk.parse_jw_block("|{LANGS}|\n{t}".format(
            LANGS=LANGS, t=f"{SUB_ROOT}/1.vi.vtt,"))
        self.assertEqual(parsed["subtitles"], {"VI": f"{SUB_ROOT}/1.vi.vtt"})
        self.assertEqual(kk.subtitle_name(None), "")
        self.assertEqual(kk.subtitle_name("en"), "English")

    def test_invisible_characters_cannot_hide_a_marker(self):
        parsed = kk.parse_jw_block("﻿*​" + slot("2"))
        self.assertTrue(parsed["hidden"])

    def test_a_group_is_split_into_one_episode_per_semicolon_block(self):
        episodes = kk.parse_jw_group(f"{slot('1')};{slot('2')};​;")
        self.assertEqual([e["episode"] for e in episodes], [1, 2])

    def test_a_pipe_inside_a_countdown_is_not_a_field_break(self):
        # The player's own splitJwFields(): `|` separates fields except inside a
        # `${…}` schedule expression, which is printed with pipes of its own.
        self.assertEqual(kk._split_head_fields("${2026-11-01|20:00}|English|"),
                         ["${2026-11-01|20:00}", "English", ""])
        parsed = kk.parse_jw_block(
            "${2026-11-01|20:00}" + slot("5"))
        self.assertEqual(parsed["scheduled"], "2026-11-01|20:00")
        self.assertEqual(parsed["episode"], 5)
        self.assertEqual(parsed["subtitle_languages"], list(kk.SUBTITLE_LANGS.values()))


class TestEmbedGroup(unittest.TestCase):
    def test_an_embed_group_becomes_one_page_per_episode(self):
        body = ("https://kisskh.asia/embed/a;https://kisskh.asia/embed/b;"
                "not a url at all;https://hlscdn.vip/media/x.mp4")
        episodes = kk.parse_embed_group(body)
        self.assertEqual([e["embed"] for e in episodes],
                         ["https://kisskh.asia/embed/a", "https://kisskh.asia/embed/b"])
        self.assertEqual(episodes[0]["video"], "")
        self.assertEqual(episodes[0]["subtitles"], {})

    def test_a_merged_embed_group_is_a_page_source_not_a_stream(self):
        merged = kk.merge_episode_groups([{"type": "embed", "body": "*https://kisskh.asia/embed/a"}])
        row = merged[1]
        self.assertEqual(row["servers"][0]["kind"], "embed")
        self.assertTrue(row["hidden"])
        source = kk.sources_for(row)[0]
        self.assertEqual((source["playback_type"], source["status"]), ("iframe", "blocked"))


class TestEpisodeIdentity(unittest.TestCase):
    def test_the_filename_is_the_episode_number_and_language(self):
        self.assertEqual(kk.episode_from_track_url(track("12", "pt")), (12, "pt"))
        self.assertEqual(kk.episode_from_track_url("https://x.cdn/a.mp4"), (None, None))
        self.assertEqual(kk.episode_from_track_url(None), (None, None))

    def test_the_same_episode_on_two_servers_becomes_one_release(self):
        groups = [{"type": "jw", "body": f"{slot('1')};{slot('2')}"},
                  {"type": "jw", "body": slot("1", video="https://chat.imostatic.com/asia_live/V4s1/a.mp4")}]
        merged = kk.merge_episode_groups(groups)
        self.assertEqual(sorted(merged), [1, 2])
        self.assertEqual(len(merged[1]["servers"]), 2)
        self.assertEqual([s["server_index"] for s in merged[1]["servers"]], [1, 2])

    def test_a_slot_without_a_numbered_track_falls_back_to_its_order(self):
        body = ("https://hlscdn.vip/media/a.mp4|" + LANGS + "|\n"
                "https://sub.cdnauto.xyz/unnumbered.en.vtt,;"
                "https://hlscdn.vip/media/b.mp4|" + LANGS + "|\n"
                "https://sub.cdnauto.xyz/unnumbered2.en.vtt,")
        merged = kk.merge_episode_groups([{"type": "jw", "body": body}])
        self.assertEqual(sorted(merged), [1, 2])
        self.assertEqual(merged[1]["subtitles"], {"English": "https://sub.cdnauto.xyz/unnumbered.en.vtt"})

    def test_a_hidden_and_a_playable_copy_of_one_episode_do_not_unhide_it(self):
        groups = [{"type": "jw", "body": slot("1")},
                  {"type": "jw", "body": slot("1", marker="*")}]
        merged = kk.merge_episode_groups(groups)
        self.assertFalse(merged[1]["hidden"])


class TestHostRules(unittest.TestCase):
    def test_a_media_host_with_a_file_is_a_stream(self):
        self.assertEqual(kk._media_kind("https://hlscdn.vip/media/a.mp4"), "video")
        self.assertEqual(kk._media_kind("https://x.sooplive.com/a/b.m3u8"), "video")
        self.assertEqual(kk._media_kind("https://pub-9bbcb2d0be3b40338fe5c1a273c7ae93.r2.dev/KR/9.mpd"),
                         "video")

    def test_a_media_host_without_a_file_is_a_bridge(self):
        self.assertEqual(kk._media_kind("https://bigf.imostatic.com"), "bridge")

    def test_a_subtitle_host_is_a_track(self):
        self.assertEqual(kk._media_kind(track("1", "en")), "subtitle")
        self.assertEqual(kk._media_kind("https://res.cloudinary.com/sub2t9/raw/upload/1.en.vtt"),
                         "subtitle")

    def test_the_site_host_itself_is_an_embed_page(self):
        self.assertEqual(kk._media_kind("https://kisskh.asia/embed/abc"), "embed")

    def test_a_picture_on_an_image_host_is_a_poster(self):
        self.assertEqual(kk._media_kind("https://image.tmdb.org/t/p/w1000/x.jpg"), "poster")

    def test_a_stranger_host_is_never_a_source(self):
        for url in ("https://ad-network.example/track.mp4", "https://short.link/x",
                    "https://", "https://kisskh-copy.example.com/a.mp4",
                    "https://images.example.com/x.png"):
            with self.subTest(url=url):
                self.assertIsNone(kk._media_kind(url))

    def test_look_alike_hosts_are_not_the_site(self):
        self.assertFalse(kk._is_site_url("https://kisskh-copy.example.com/the-drama/"))
        self.assertTrue(kk._is_site_url("https://kisskh.asia/the-drama/"))

    def test_a_manifest_is_named_after_its_folder(self):
        self.assertEqual(kk._resource_id(
            "https://x.sooplive.com/spkt/save/a/2026-10-27/21/1793103606106422.mp4/manifest.m3u8"),
            "1793103606106422")
        self.assertEqual(kk._resource_id(track("3", "hi")), "3.hi")
        self.assertEqual(kk._resource_id("https://host/no-extension"), "no-extension")
        self.assertEqual(kk._resource_id("https://host/"), "")

    def test_signed_object_urls_are_marked_temporary(self):
        self.assertEqual(kk._is_temporary("https://chat.imostatic.com/asia_live/V4s2/TOKEN.mp4"), 1)
        self.assertEqual(kk._is_temporary("https://pub-abc.r2.dev/x.m3u8?X-Amz-Signature=1"), 1)
        self.assertEqual(kk._is_temporary(track("1", "en")), 0)
        self.assertEqual(kk._is_temporary(""), 0)

    def test_the_referer_rule_matches_the_players_own_list(self):
        self.assertTrue(kk.needs_referrer("https://hlscdn.vip/media/a.mp4"))
        self.assertTrue(kk.needs_referrer("https://cdn.hlscdn.vip/a.mp4"))
        self.assertFalse(kk.needs_referrer("https://chat.imostatic.com/asia_live/a.mp4"))
        self.assertFalse(kk.needs_referrer(""))


class TestWpRecord(unittest.TestCase):
    def test_terms_are_resolved_by_taxonomy_and_deduplicated(self):
        terms = kk.terms_from_embed(wp_record(terms=[
            term_group("genre", "Romance", "Supernatural")
            + term_group("genre", "Supernatural", "Thriller")]))
        self.assertEqual(terms["genre"], ["Romance", "Supernatural", "Thriller"])

    def test_an_empty_term_name_is_not_a_term(self):
        terms = kk.terms_from_embed({"_embedded": {"wp:term": [[
            {"taxonomy": "genre", "name": "  "}, {"taxonomy": "", "name": "Drama"}]]}})
        self.assertEqual(terms, {"term": ["Drama"]})
        self.assertEqual(kk.terms_from_embed({}), {})

    def test_an_empty_synopsis_is_a_null_not_an_empty_string(self):
        self.assertIsNone(kk.build_post(wp_record(), {"html": blob(eps=("1",))})["synopsis"])
        post = kk.build_post(wp_record(content="<p>Twenty episodes of&nbsp; chaos.</p>"),
                             {"html": blob(eps=("1",))})
        self.assertEqual(post["synopsis"], "Twenty episodes of chaos.")

    def test_a_placeholder_synopsis_is_a_null(self):
        self.assertIsNone(kk._meaningful("N/A"))
        self.assertIsNone(kk._meaningful(" —., "))
        self.assertIsNone(kk._meaningful(None))
        self.assertEqual(kk._meaningful("Real prose."), "Real prose.")

    def test_the_featured_image_wins_and_the_blob_image_is_the_fallback(self):
        record = wp_record(media="")
        record["_embedded"]["wp:featuredmedia"] = [{"source_url": "//bad"}, {}]
        post = kk.build_post(record, {"html": blob(eps=("1",))})
        self.assertEqual(post["poster_url"], "https://image.tmdb.org/t/p/w1000/p.jpg")
        self.assertEqual(kk.poster_from_embed({}), "")

    def test_a_record_without_id_link_or_slug_is_not_a_catalog_entry(self):
        for broken in ({"slug": "x", "link": "https://kisskh.asia/x/"},
                       {"id": 1, "link": "", "slug": "x"},
                       {"id": 1, "link": "https://kisskh.asia/x/", "slug": ""},
                       {"id": 1, "link": "https://kisskh.asia/x/", "slug": "x",
                        "title": {"rendered": "Kisskh"}}):
            with self.subTest(broken=broken):
                self.assertIsNone(kk.build_post(broken, {"html": blob(eps=("1",))}))

    def test_site_branding_never_reaches_a_display_string(self):
        self.assertEqual(kk.scrub_brand("Love Ridden — kisskh"), "Love Ridden —")
        self.assertEqual(kk.scrub_brand(None), "")
        post = kk.build_post(wp_record(title="My Drama kisskh"), {"html": blob(eps=("1",))})
        self.assertEqual(post["clean_title"], "My Drama")
        self.assertEqual(post["title"], "My Drama kisskh")

    def test_the_shelf_decides_media_type_and_the_episode_count_is_the_fallback(self):
        self.assertEqual(kk.media_type_for({"category": ["Movie"]}, 1), "movie")
        self.assertEqual(kk.media_type_for({"genre": ["Drama"]}, 1), "series")
        self.assertEqual(kk.media_type_for({"genre": ["Sitcom"]}, 9), "series")
        self.assertEqual(kk.media_type_for({"genre": ["Fantasy"]}, 1), "movie")
        self.assertEqual(kk.media_type_for({"genre": ["Fantasy"]}, 4), "series")

    def test_the_subtitle_set_is_what_the_catalog_offers_not_an_audio_claim(self):
        post = kk.build_post(wp_record(), {"html": blob(eps=("1", "2"))})
        self.assertEqual(post["languages"], ", ".join(kk.SUBTITLE_LANGS.values()))
        self.assertIsNone(post["releases"][0]["audio_languages"])
        self.assertEqual(post["releases"][0]["label"], "Episode 1")

    def test_a_movie_with_one_slot_is_labelled_as_one_work(self):
        post = kk.build_post(wp_record(terms=term_group("category", "Movie")),
                             {"html": blob(eps=("1",))})
        self.assertEqual(post["media_type"], "movie")
        self.assertEqual(post["releases"][0]["label"], "Full Movie")

    def test_country_names_the_industry(self):
        post = kk.build_post(wp_record(), {"html": blob(eps=("1",))})
        self.assertEqual(post["country"], "Korean")
        self.assertEqual(kk.classify(post)["industry"], "K-Drama")
        self.assertEqual(kk.classify({"country": ""})["country"], None)
        self.assertEqual(kk.classify({"country": "United States"})["industry"], None)
        self.assertEqual(kk.classify({})["media_type"], "series")

    def test_the_raw_record_keeps_the_ids_the_site_gave_us(self):
        post = kk.build_post(wp_record(), {"html": blob(eps=("1", "2")), "source": "blogger",
                                           "updated": "2026-09-08T01:10:28", "blogId": "810",
                                           "title": "274559"})
        meta = post["raw_meta"]
        self.assertEqual(meta["wp_post_id"], 101)
        self.assertEqual(meta["blog_id"], "810")
        self.assertEqual(meta["site_media_id"], "274559")
        self.assertIsNone(post["tmdb_id"])
        self.assertEqual(len(meta["episodes"]), 2)
        self.assertEqual(len(meta["episodes"][0]["subtitles"]), 11)

    def test_a_record_with_no_blob_yields_no_releases(self):
        post = kk.build_post(wp_record(), None)
        self.assertEqual(post["releases"], [])
        self.assertEqual(post["episodes"], {})


class TestAdultAndAnimatedFlags(unittest.TestCase):
    def test_an_erotic_shelf_flags_the_title(self):
        terms = {"post_tag": ["Erotic Thriller"]}
        self.assertEqual(kk.is_adult(terms, "Verity"), 1)

    def test_an_older_marker_flags_too(self):
        for marker in ("18+", "18 plus", "Adult", "Uncensored"):
            with self.subTest(marker=marker):
                self.assertEqual(kk.is_adult({"genre": [marker]}, "Something"), 1)

    def test_a_mainstream_drama_is_not_flagged(self):
        self.assertEqual(kk.is_adult({"genre": ["Romance", "Youth"]}, "First Love"), 0)
        self.assertEqual(kk.is_adult({"genre": ["Sexual Healing"]}, "Night Bus"), 0)

    def test_a_synopsis_alone_never_flags_a_title(self):
        terms = {"genre": ["Mystery"]}
        self.assertEqual(kk.is_adult(terms, "The Silent Patient"), 0)

    def test_animated_shelves_flag_animation(self):
        self.assertEqual(kk.looks_animated({"genre": ["Animation"]}, "X"), 1)
        self.assertEqual(kk.looks_animated({}, "Studio Ghibli Tale"), 0)


class TestSourcesAndReleases(unittest.TestCase):
    def test_a_hidden_slot_is_blocked_and_a_playable_one_is_unverified(self):
        merged = kk.merge_episode_groups([{"type": "jw", "body": f"{slot('1')};{slot('2', marker='*')}"}])
        sources = {n: kk.sources_for(row) for n, row in merged.items()}
        self.assertEqual(sources[1][0]["status"], "unverified")
        self.assertEqual(sources[2][0]["status"], "blocked")
        self.assertEqual(sources[2][0]["playback_type"], "stream")
        # The form the site really publishes for an unairable slot: a bare host.
        bare = kk.merge_episode_groups([{"type": "jw", "body": slot("3", marker="*",
                                                                   video="https://bigf.imostatic.com")}])
        self.assertEqual(kk.sources_for(bare[3])[0]["playback_type"], "iframe")
        self.assertEqual(kk.sources_for(bare[3])[0]["status"], "blocked")

    def test_a_page_source_is_recorded_as_needing_the_page(self):
        row = {"servers": [{"server_index": 1, "kind": "embed", "url": "https://x.sooplive.com/live/a",
                            "hidden": False, "scheduled": None}], "subtitles": {}}
        src = kk.sources_for(row)[0]
        self.assertEqual(src["playback_type"], "iframe")
        self.assertEqual(src["status"], "js_required")

    def test_a_stranger_host_in_the_blob_never_becomes_a_source(self):
        row = {"servers": [{"server_index": 1, "kind": "jw", "url": "https://ads.example/x.mp4",
                            "hidden": False, "scheduled": None}],
               "subtitles": {"English": "https://ads.example/1.en.vtt"}}
        self.assertEqual(kk.sources_for(row), [])

    def test_tracks_are_one_row_per_language_and_sorted(self):
        merged = kk.merge_episode_groups([{"type": "jw", "body": slot("1")}])
        tracks_rows = kk.sources_for(list(merged.values())[0])
        subs = [r for r in tracks_rows if r["playback_type"] == "subtitle"]
        self.assertEqual(len(subs), 11)
        self.assertEqual([s["source_name"] for s in subs][:3], ["Arabic", "English", "Filipino"])
        self.assertTrue(all(s["status"] == "unverified" for s in subs))

    def test_a_release_without_a_server_is_not_stored(self):
        releases = kk.releases_for({}, {1: {"episode": 1, "servers": [], "subtitles": {}}})
        self.assertEqual(releases, [])


class TestResolveLinks(unittest.TestCase):
    def post(self):
        return kk.build_post(wp_record(), {"html": blob(eps=("1", "2"))})

    def test_without_a_probe_only_the_referer_rule_is_recorded(self):
        post = kk.resolve_links(self.post(), probe=False)
        src = post["releases"][0]["sources"][0]
        self.assertTrue(src["needs_referer"])
        self.assertIsNone(src["last_checked"])
        self.assertEqual(post["resolved"], {"probe": False, "deep": False})

    def test_a_probe_records_the_verdict_for_tracks_too(self):
        with mock.patch.object(kk, "probe_source",
                               return_value={"status_code": 403, "status": "blocked",
                                             "location": None, "checked_with_referer": True}):
            post = kk.resolve_links(self.post(), probe=True)
        statuses = {(s["source_name"], s["playback_type"]): s["status"]
                    for r in post["releases"] for s in r["sources"]}
        self.assertEqual(statuses[("Server 1", "stream")], "blocked")
        self.assertEqual(statuses[("English", "subtitle")], "blocked")
        self.assertTrue(all(s["last_checked"] for r in post["releases"] for s in r["sources"]))

    def test_an_unprobed_row_never_claims_a_check_that_did_not_happen(self):
        post = kk.resolve_links(self.post(), probe=False)
        rows = [s for r in post["releases"] for s in r["sources"]]
        self.assertTrue(all(s["status"] == "unverified" for s in rows))
        self.assertTrue(all(s["last_checked"] is None for s in rows))

    def test_a_deep_probe_stores_the_redirect_target(self):
        post = self.post()
        with mock.patch.object(kk, "http_get_once",
                               return_value=(302, "//cdn.example/paid.mp4", "")):
            kk.resolve_links(post, probe=True, deep=True)
        self.assertEqual(post["releases"][0]["sources"][0]["final_url"],
                         "https://cdn.example/paid.mp4")

    def test_a_source_needing_no_referer_is_probed_without_one(self):
        post = kk.build_post(wp_record(), {"html": blob(eps=("1",)).replace(
            "https://hlscdn.vip/media/file1.mp4", "https://chat.imostatic.com/asia_live/V4s1/x.mp4")})
        seen = {}

        def fake_once(url, referer=None, timeout=25):
            seen["referer"] = referer
            return 200, None, ""

        with mock.patch.object(kk, "http_get_once", side_effect=fake_once):
            kk.resolve_links(post, probe=True)
        self.assertIsNone(seen["referer"])

    def test_probe_verdicts_are_mapped_honestly(self):
        with mock.patch.object(kk, "http_get_once", return_value=(206, None, "")):
            self.assertEqual(kk.probe_source("https://hlscdn.vip/a.mp4")["status"], "active")
        for code, verdict in ((204, "blocked"), (404, "dead"), (429, "unknown"),
                              (0, "error"), (599, "unknown")):
            with self.subTest(code=code), mock.patch.object(kk, "http_get_once",
                                                            return_value=(code, None, "")):
                self.assertEqual(kk.probe_source("https://x/a.mp4")["status"], verdict)


class TestStagingDatabase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = Path(self.tmp) / "kisskh.db"

    def post(self, slug="test-drama", eps=("1", "2")):
        return kk.build_post(wp_record(slug=slug), {"html": blob(eps=eps)})

    def test_the_schema_is_the_shared_staging_shape(self):
        kk.export_staging(self.db, [self.post()])
        conn = sqlite3.connect(self.db)
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertEqual(tables, {"sitemap_cache", "posts", "releases", "sources",
                                  "sqlite_sequence"})
        release_cols = {r[1] for r in conn.execute("PRAGMA table_info(releases)")}
        self.assertIn("post_canonical_key", release_cols)
        self.assertEqual(conn.execute("SELECT source_site FROM posts").fetchone()[0], "kisskh")
        conn.close()

    def test_a_legacy_database_is_upgraded_not_rejected(self):
        conn = sqlite3.connect(self.db)
        conn.executescript(
            "CREATE TABLE posts (canonical_key TEXT PRIMARY KEY, title TEXT NOT NULL,"
            " clean_title TEXT NOT NULL, media_type TEXT, url TEXT, slug TEXT,"
            " source_site TEXT, raw_meta TEXT);"
            "CREATE TABLE releases (id INTEGER PRIMARY KEY, post_canonical_key TEXT,"
            " label TEXT, bridge_url TEXT);"
            "CREATE TABLE sources (id INTEGER PRIMARY KEY, release_id INTEGER,"
            " source_name TEXT, service TEXT, source_url TEXT);")
        conn.commit()
        conn.close()
        kk.ensure_schema(sqlite3.connect(self.db))
        cols = {r[1] for r in sqlite3.connect(self.db).execute("PRAGMA table_info(posts)")}
        self.assertTrue({"industry", "country", "duration", "seasons"} <= cols)
        rel_cols = {r[1] for r in sqlite3.connect(self.db).execute("PRAGMA table_info(releases)")}
        self.assertIn("origin_url", rel_cols)
        # The indexes are built on sources.status / sources.playback_type, so an
        # older sources table has to gain them before ensure_schema can finish.
        src_cols = {r[1]: r[2] for r in sqlite3.connect(self.db).execute(
            "PRAGMA table_info(sources)")}
        self.assertEqual((src_cols["status"], src_cols["playback_type"]), ("TEXT", "TEXT"))
        self.assertEqual(src_cols["last_checked"], "INTEGER")
        self.assertEqual(sorted({r[0] for r in sqlite3.connect(self.db).execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_kisskh%'")}),
            ["idx_kisskh_posts_country", "idx_kisskh_posts_slug",
             "idx_kisskh_releases_post", "idx_kisskh_sources_playback",
             "idx_kisskh_sources_status"])
        self.assertEqual(kk.export_staging(self.db, [self.post()])["sources_written"], 24)

    def test_a_re_import_refreshes_without_multiplying_rows(self):
        post = self.post()
        kk.export_staging(self.db, [post])
        again = kk.export_staging(self.db, [self.post()])
        self.assertEqual(again["releases_written"], 2)
        conn = sqlite3.connect(self.db)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM releases").fetchone()[0], 2)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0], 24)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0], 1)
        conn.close()

    def test_an_incomplete_post_is_skipped_not_stored(self):
        totals = kk.export_staging(self.db, [None, {"clean_title": "x"},
                                              {"canonical_key": "k", "clean_title": "t",
                                               "releases": []},
                                              self.post()])
        self.assertEqual(totals["skipped"], 3)
        self.assertEqual(totals["posts_written"], 1)
        self.assertEqual(kk.export_staging(self.db), {"posts_written": 0, "releases_written": 0,
                                                     "sources_written": 0, "skipped": 0})

    def test_stats_counts_tracks_and_playback_separately(self):
        kk.export_staging(self.db, [self.post()])
        out = kk.stats(self.db)
        self.assertEqual(out["posts"], 1)
        self.assertEqual(out["releases"], 2)
        self.assertEqual(out["sources"], 24)
        self.assertEqual(out["subtitle_tracks"], 22)
        self.assertEqual(out["playback_types"], {"stream": 2, "subtitle": 22})
        self.assertEqual(out["indexed"], 1)
        self.assertEqual(out["queued"], 0)
        self.assertEqual(out["countries"], {"Korean": 1})

    def test_no_orphans_and_no_duplicate_keys(self):
        kk.export_staging(self.db, [self.post(), self.post(slug="second-drama")])
        conn = sqlite3.connect(self.db)
        self.assertEqual(conn.execute(
            "SELECT COUNT(*) FROM releases r LEFT JOIN posts p"
            " ON p.canonical_key = r.post_canonical_key WHERE p.canonical_key IS NULL").
            fetchone()[0], 0)
        self.assertEqual(conn.execute(
            "SELECT COUNT(*) FROM sources s LEFT JOIN releases r ON r.id = s.release_id"
            " WHERE r.id IS NULL").fetchone()[0], 0)
        self.assertEqual(conn.execute(
            "SELECT COUNT(DISTINCT canonical_key) FROM posts").fetchone()[0], 2)
        conn.close()

    def test_a_release_carries_no_site_branding_in_its_label(self):
        kk.export_staging(self.db, [self.post()])
        conn = sqlite3.connect(self.db)
        conn.row_factory = sqlite3.Row
        labels = [r["label"] for r in conn.execute("SELECT label FROM releases")]
        self.assertEqual(labels, ["Episode 1", "Episode 2"])
        self.assertNotIn("kisskh", json.dumps([dict(r) for r in conn.execute(
            "SELECT * FROM sources")], ensure_ascii=False).lower().replace(
                '"service": "kisskh.asia"', ""))
        conn.close()


class TestSyncQueue(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = Path(self.tmp) / "kisskh.db"

    def test_the_rest_pages_are_walked_until_a_short_page(self):
        pages = {1: [wp_record(pid=i) for i in range(kk.PAGE_SIZE)],
                 2: [wp_record(pid=900)]}
        asked = []

        def fake(url, timeout=30):
            asked.append((url, timeout))
            page = int(url.split("&page=")[1].split("&")[0])
            return 200, f"{kk.REST_POSTS}?page={page}", json.dumps(pages.get(page, []))

        with silenced(), mock.patch.object(kk, "http_get", side_effect=fake):
            records = list(kk.iter_catalog_posts())
        self.assertEqual(len(records), kk.PAGE_SIZE + 1)
        # The embedded listing is multi-megabyte: per_page=20 with a 60 s budget is
        # what this host can actually answer. The default 30 s stalls page 1 at 0.
        self.assertEqual([t for _, t in asked], [kk.LISTING_TIMEOUT] * 2)
        self.assertIn("per_page=20", asked[0][0])
        self.assertEqual(kk.PAGE_SIZE, 20)

    def test_a_failed_page_and_a_non_list_answer_both_stop_the_walk(self):
        with silenced() as out, mock.patch.object(kk, "http_get", return_value=(500, "", "")):
            self.assertEqual(list(kk.iter_catalog_posts()), [])
        self.assertIn("page 1 -> HTTP 500", out.getvalue())
        with silenced() as out, \
                mock.patch.object(kk, "http_get",
                                  return_value=(200, "", '{"code":"no_route"}')):
            self.assertEqual(list(kk.iter_catalog_posts()), [])
        self.assertIn("page 1 is not a post list", out.getvalue())
        with silenced(), mock.patch.object(kk, "http_get", return_value=(200, "", "[]")):
            self.assertEqual(list(kk.iter_catalog_posts()), [])

    def test_sync_queues_each_drama_once_and_carries_its_record(self):
        records = [wp_record(pid=1, slug="alpha"), wp_record(pid=2, slug="alpha"),
                   {"id": 3, "slug": "beta", "link": "https://elsewhere.example/beta/",
                    "title": {"rendered": "Beta"}, "_embedded": {}}]
        with mock.patch.object(kk, "iter_catalog_posts", return_value=iter(records)):
            queued = kk.sync_catalog(db_path=self.db, verbose=False)
        self.assertEqual(queued, 1)
        conn = sqlite3.connect(self.db)
        loc, raw = conn.execute("SELECT loc, raw_json FROM sitemap_cache").fetchone()
        self.assertEqual(loc, "https://kisskh.asia/alpha/")
        self.assertEqual(json.loads(raw)["id"], 1)
        conn.close()

    def test_sync_requeues_a_row_the_previous_run_left_in_state_two(self):
        with mock.patch.object(kk, "iter_catalog_posts",
                               return_value=iter([wp_record(pid=1, slug="alpha")])):
            kk.sync_catalog(db_path=self.db, verbose=False)
        conn = sqlite3.connect(self.db)
        conn.execute("UPDATE sitemap_cache SET scraped = 2 WHERE loc LIKE '%alpha%';")
        conn.commit()
        conn.close()
        with mock.patch.object(kk, "iter_catalog_posts", return_value=iter([])):
            kk.sync_catalog(db_path=self.db, verbose=False)
        states = [r[0] for r in sqlite3.connect(self.db).execute(
            "SELECT scraped FROM sitemap_cache")]
        self.assertEqual(states, [0])

    def test_sync_reports_what_it_queued_and_survives_an_empty_catalog(self):
        # The operator-facing lines are asserted, not streamed: suite output stays
        # clean and a change to the wording fails a test instead of going unseen.
        with mock.patch.object(kk, "iter_catalog_posts",
                               return_value=iter([wp_record(pid=1)])), \
                silenced() as out:
            self.assertEqual(kk.sync_catalog(db_path=self.db, limit=1), 1)
        self.assertIn("Queued 1 dramas (1 new, 1 total).", out.getvalue())
        with mock.patch.object(kk, "iter_catalog_posts", return_value=iter([])), \
                silenced() as out:
            self.assertEqual(kk.sync_catalog(db_path=self.db, verbose=True), 0)
        self.assertIn("No catalog entries returned", out.getvalue())

    def test_a_body_that_is_not_json_is_reported_not_stored(self):
        with silenced() as out, mock.patch.object(kk, "http_get", return_value=(200, "", "<html>")):
            status, payload = kk.get_json("https://kisskh.asia/x")
        self.assertEqual((status, payload), (200, None))
        self.assertIn("is not JSON", out.getvalue())
        with mock.patch.object(kk, "http_get", return_value=(404, "", "{}")):
            self.assertEqual(kk.get_json("https://kisskh.asia/x"), (404, None))

    def test_a_slug_lookup_returns_the_first_record_the_api_gives(self):
        with mock.patch.object(kk, "http_get", return_value=(200, "", json.dumps(
                [wp_record(pid=42, slug="late-record")]))) as fetched:
            self.assertEqual(kk._fetch_post_by_slug("late record")["id"], 42)
        self.assertIn("slug=late%20record", fetched.call_args[0][0])
        for answer in ((200, "", "[]"), (200, "", "null"), (500, "", "")):
            with self.subTest(answer=answer), \
                    mock.patch.object(kk, "http_get", return_value=answer):
                self.assertIsNone(kk._fetch_post_by_slug("gone"))

    def test_a_player_answer_is_only_useful_if_it_carries_a_blob(self):
        with mock.patch.object(kk, "http_get", return_value=(200, "", json.dumps(
                {"html": blob(eps=("1",))}))):
            self.assertIsNotNone(kk.fetch_player_blob(1)[1])
        for answer in ((200, "", '{"code":"no_data"}'), (200, "", "[]"), (404, "", "")):
            with self.subTest(answer=answer), \
                    mock.patch.object(kk, "http_get", return_value=answer) as fetched:
                status, payload = kk.fetch_player_blob(1)
            self.assertIsNone(payload)
            self.assertEqual(status, answer[0])
        self.assertIn("post=1", fetched.call_args[0][0])


class TestCrawl(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = Path(self.tmp) / "kisskh.db"
        self.record = wp_record(pid=77, slug="crawled-drama")
        conn = sqlite3.connect(self.db)
        kk.ensure_schema(conn)
        conn.execute("INSERT INTO sitemap_cache (loc, slug, raw_json) VALUES (?, ?, ?)",
                     (self.record["link"], self.record["slug"], json.dumps(self.record)))
        conn.commit()
        conn.close()

    def test_the_queue_is_drained_into_posts_releases_and_tracks(self):
        with mock.patch.object(kk, "http_get", return_value=(200, "", json.dumps(
                {"html": blob(eps=("1", "2"))}))), silenced() as out:
            totals = kk.crawl_pending(db_path=self.db, workers=1, delay=0, verbose=True)
        self.assertEqual(totals["posts"], 1)
        self.assertEqual(totals["releases"], 2)
        self.assertEqual(totals["sources"], 24)
        self.assertIn("dramas=1 posts=1 releases=2 sources=24", out.getvalue())
        self.assertEqual(kk.stats(self.db)["queued"], 0)

    def test_a_batch_flush_is_per_drama_size(self):
        with mock.patch.object(kk, "http_get", return_value=(200, "", json.dumps(
                {"html": blob(eps=("1",))}))):
            totals = kk.crawl_pending(db_path=self.db, workers=1, delay=0,
                                      batch_size=1, verbose=False)
        self.assertEqual(totals["posts"], 1)

    def test_a_drama_with_no_blob_is_requeued_for_the_next_crawl(self):
        with mock.patch.object(kk, "http_get", return_value=(200, "", '{"code":"no_data"}')):
            for _ in range(4):
                kk.crawl_pending(db_path=self.db, workers=1, delay=0, verbose=False)
        row = sqlite3.connect(self.db).execute(
            "SELECT scraped, error_count, raw_json FROM sitemap_cache").fetchone()
        # An unpublished drama is not a dead one: four sightings later it is still
        # queued, and the record the crawl needs is still in the row.
        self.assertEqual((row[0], row[1]), (2, 4))
        self.assertEqual(json.loads(row[2])["id"], 77)

    def test_a_post_the_site_no_longer_resolves_is_parked_at_once(self):
        conn = sqlite3.connect(self.db)
        conn.execute("UPDATE sitemap_cache SET raw_json = ?", (json.dumps({"slug": "gone"}),))
        conn.commit()
        conn.close()
        with mock.patch.object(kk, "_fetch_post_by_slug", return_value=None):
            kk.crawl_pending(db_path=self.db, workers=1, delay=0, verbose=False)
        row = sqlite3.connect(self.db).execute(
            "SELECT scraped, error_count FROM sitemap_cache").fetchone()
        self.assertEqual(row[0], -1)

    def test_a_transport_error_gets_three_strikes_before_it_is_parked(self):
        with mock.patch.object(kk, "http_get", return_value=(0, "", "[network error] timeout")):
            for _ in range(3):
                kk.crawl_pending(db_path=self.db, workers=1, delay=0, verbose=False)
                parked = sqlite3.connect(self.db).execute(
                    "SELECT scraped, error_count FROM sitemap_cache").fetchone()
                if parked[0] == -1:
                    break
        self.assertEqual(parked[0], -1)
        self.assertLessEqual(parked[1], 3)

    def test_a_broken_queue_record_is_refetched_by_slug(self):
        conn = sqlite3.connect(self.db)
        conn.execute("UPDATE sitemap_cache SET raw_json = 'not json';")
        conn.commit()
        conn.close()
        with mock.patch.object(kk, "_fetch_post_by_slug", return_value=None), \
                mock.patch.object(kk, "http_get", return_value=(200, "", "{}")):
            totals = kk.crawl_pending(db_path=self.db, workers=1, delay=0, verbose=False)
        self.assertEqual(totals["not_indexable"], 1)

    def test_a_record_that_got_wedged_in_the_queue_is_recovered(self):
        conn = sqlite3.connect(self.db)
        conn.execute("UPDATE sitemap_cache SET raw_json = ?", (json.dumps({"slug": "x"}),))
        conn.commit()
        conn.close()
        with mock.patch.object(kk, "_fetch_post_by_slug", return_value=self.record), \
                mock.patch.object(kk, "http_get",
                                  return_value=(200, "", json.dumps({"html": blob(eps=("1",))}))):
            totals = kk.crawl_pending(db_path=self.db, workers=1, delay=0, verbose=False)
        self.assertEqual(totals["posts"], 1)

    def test_a_worker_that_throws_is_counted_failed_not_lost(self):
        with mock.patch.object(kk, "_parse_record", side_effect=RuntimeError("boom")):
            totals = kk.crawl_pending(db_path=self.db, workers=1, delay=0, verbose=False)
        self.assertEqual(totals["failed"], 1)
        self.assertEqual(sqlite3.connect(self.db).execute(
            "SELECT COUNT(*) FROM sitemap_cache WHERE error_count = 1").fetchone()[0], 1)

    def test_a_probe_that_throws_still_keeps_the_catalog(self):
        with mock.patch.object(kk, "resolve_links", side_effect=RuntimeError("chain died")), \
                mock.patch.object(kk, "http_get", return_value=(200, "", json.dumps(
                    {"html": blob(eps=("1",))}))):
            totals = kk.crawl_pending(db_path=self.db, workers=1, delay=0, verbose=False)
        self.assertEqual(totals["posts"], 1)
        self.assertEqual(kk.stats(self.db)["posts"], 1)

    def test_the_stop_flag_drains_the_pool_instead_of_abandoning_it(self):
        kk.STOP_REQUESTED = True
        try:
            totals = kk.crawl_pending(db_path=self.db, workers=2, delay=0, verbose=False)
        finally:
            kk.STOP_REQUESTED = False
        self.assertEqual(totals["posts"], 0)
        self.assertEqual(totals["pages"], 0)

    def test_a_stop_asked_part_way_leaves_the_rest_of_the_queue_alone(self):
        second = wp_record(pid=78, slug="crawled-later")
        conn = sqlite3.connect(self.db)
        conn.execute("INSERT INTO sitemap_cache (loc, slug, raw_json) VALUES (?, ?, ?)",
                     (second["link"], second["slug"], json.dumps(second)))
        conn.commit()
        conn.close()
        calls = []

        def parse(loc, raw_json, slug):
            calls.append(slug)
            kk.STOP_REQUESTED = True
            return kk.build_post(json.loads(raw_json), {"html": blob(eps=("1",))}), "ok"

        try:
            with mock.patch.object(kk, "_parse_record", side_effect=parse):
                totals = kk.crawl_pending(db_path=self.db, workers=1, delay=0, verbose=False)
        finally:
            kk.STOP_REQUESTED = False
        self.assertEqual(len(calls), 1)
        self.assertEqual((totals["pages"], totals["posts"]), (1, 1))
        states = [r[0] for r in sqlite3.connect(self.db).execute(
            "SELECT scraped FROM sitemap_cache ORDER BY scraped")]
        self.assertEqual(states, [0, 1])

    def test_a_limit_caps_the_run_and_leaves_the_queue_for_next_time(self):
        second = wp_record(pid=79, slug="crawled-later")
        conn = sqlite3.connect(self.db)
        conn.execute("INSERT INTO sitemap_cache (loc, slug, raw_json) VALUES (?, ?, ?)",
                     (second["link"], second["slug"], json.dumps(second)))
        conn.commit()
        conn.close()
        with mock.patch.object(kk, "http_get", return_value=(200, "", json.dumps(
                {"html": blob(eps=("1",))}))):
            totals = kk.crawl_pending(limit=1, db_path=self.db, workers=1, delay=0,
                                      verbose=False)
        self.assertEqual(totals["posts"], 1)
        self.assertEqual(kk.stats(self.db)["queued"], 1)

    def test_an_empty_queue_returns_without_a_thread_pool(self):
        conn = sqlite3.connect(self.db)
        conn.execute("DELETE FROM sitemap_cache;")
        conn.commit()
        conn.close()
        with mock.patch.object(kk, "_bump_error") as bump, \
                mock.patch.object(kk, "http_get") as fetched:
            totals = kk.crawl_pending(db_path=self.db, workers=1, delay=0, verbose=False)
        self.assertEqual(totals["pages"], 0)
        bump.assert_not_called()
        fetched.assert_not_called()

    def test_a_declined_drama_records_why_in_the_queue_row(self):
        kk._bump_error(self.db, self.record["link"], "no-player-data")
        row = json.loads(sqlite3.connect(self.db).execute(
            "SELECT raw_json FROM sitemap_cache").fetchone()[0])
        self.assertEqual(row["last_note"], "no-player-data")
        kk._bump_error(self.db, "", "nowhere to write")


class TestParsePage(unittest.TestCase):
    def test_one_drama_by_its_page_url(self):
        record = wp_record(pid=5)
        with mock.patch.object(kk, "_fetch_post_by_slug", return_value=record), \
                mock.patch.object(kk, "http_get", return_value=(200, "", json.dumps(
                    {"html": blob(eps=("1", "2"))}))):
            post = kk.parse_page("https://kisskh.asia/test-drama/")
        self.assertEqual(post["canonical_key"], "test-drama")
        self.assertEqual(len(post["releases"]), 2)

    def test_a_percent_encoded_slug_is_encoded_exactly_once(self):
        cjk = "고려전"
        encoded = urllib.parse.quote(cjk)
        seen = {}

        def lookup(slug):
            seen["slug"] = slug
            return None

        with mock.patch.object(kk, "_fetch_post_by_slug", side_effect=lookup):
            self.assertIsNone(kk.parse_page(f"https://kisskh.asia/{encoded}/"))
        self.assertEqual(seen["slug"], cjk)
        with mock.patch.object(kk, "http_get", return_value=(200, "", "[]")) as fetched:
            kk._fetch_post_by_slug(seen["slug"])
        self.assertIn(f"slug={encoded}&", fetched.call_args[0][0])

    def test_a_url_that_is_not_a_drama_is_not_a_post(self):
        with mock.patch.object(kk, "_fetch_post_by_slug", return_value=None):
            self.assertIsNone(kk.parse_page("https://kisskh.asia/explore/"))
        self.assertIsNone(kk.parse_page("https://kisskh.asia/"))

    def test_a_drama_with_no_player_data_is_declined_once(self):
        record = wp_record(pid=5)
        with mock.patch.object(kk, "http_get", return_value=(200, "", '{"code":"rest_no_data"}')):
            post, verdict = kk._parse_record(record["link"], json.dumps(record), record["slug"])
        self.assertEqual((post, verdict), (None, "no-player-data"))

    def test_a_player_route_that_answered_gone_is_a_removed_drama(self):
        record = wp_record(pid=5)
        for code in (404, 410, 403):
            with self.subTest(code=code), mock.patch.object(
                    kk, "http_get", return_value=(code, "", "")):
                post, verdict = kk._parse_record(record["link"], json.dumps(record),
                                                 record["slug"])
            self.assertEqual((post, verdict), (None, "removed"))

    def test_a_player_route_that_is_down_is_a_transport_error(self):
        record = wp_record(pid=5)
        with mock.patch.object(kk, "http_get", return_value=(503, "", "")):
            post, verdict = kk._parse_record(record["link"], json.dumps(record),
                                             record["slug"])
        self.assertEqual((post, verdict), (None, "http-error"))

    def test_a_record_the_cleaner_refuses_is_not_a_post(self):
        broken = wp_record(pid=5, title="Kisskh")
        with mock.patch.object(kk, "http_get", return_value=(200, "", json.dumps(
                {"html": blob(eps=("1",))}))):
            post, verdict = kk._parse_record(broken["link"], json.dumps(broken),
                                             broken["slug"])
        self.assertEqual((post, verdict), (None, "not-a-post"))


class TestSeams(unittest.TestCase):
    def test_a_good_request_returns_status_body_and_final_url(self):
        resp = FakeResponse("hello", status=200, url="https://kisskh.asia/final")
        with mock.patch.object(kk._OPENER, "open", return_value=resp):
            self.assertEqual(kk.http_get("https://kisskh.asia/x"), (200, "https://kisskh.asia/final", "hello"))

    def test_a_response_without_a_status_attribute_is_treated_as_ok(self):
        resp = FakeResponse("ok")
        del resp.status
        with mock.patch.object(kk._OPENER, "open", return_value=resp):
            self.assertEqual(kk.http_get("https://kisskh.asia/x")[0], 200)

    def test_a_server_error_is_retried_then_reported(self):
        calls = []

        def flaky(url, timeout=30):
            calls.append(url)
            if len(calls) < 3:
                raise http_error(500, "busy")
            return FakeResponse("recovered")

        with mock.patch.object(kk._OPENER, "open", side_effect=flaky), \
                mock.patch.object(kk.time, "sleep") as slept:
            status, _, body = kk.http_get("https://kisskh.asia/x")
        self.assertEqual((status, body), (200, "recovered"))
        self.assertEqual(slept.call_count, 2)

    def test_a_gate_is_not_retried(self):
        for code in (401, 403, 404, 410):
            with self.subTest(code=code), mock.patch.object(
                    kk._OPENER, "open", side_effect=http_error(code, "gone")) as opened, \
                    mock.patch.object(kk.time, "sleep"):
                self.assertEqual(kk.http_get("https://kisskh.asia/x")[0], code)
                self.assertEqual(opened.call_count, 1)

    def test_a_body_that_cannot_be_read_is_described_not_raised(self):
        with mock.patch.object(kk._OPENER, "open", side_effect=http_error(500, readable=False)), \
                mock.patch.object(kk.time, "sleep"):
            status, _, body = kk.http_get("https://kisskh.asia/x", retries=1)
        self.assertEqual(status, 500)
        self.assertTrue(body.startswith("[unreadable error body]"))

    def test_a_socket_failure_is_a_status_zero_never_an_exception(self):
        with mock.patch.object(kk._OPENER, "open", side_effect=OSError("connection reset")), \
                mock.patch.object(kk.time, "sleep"):
            status, _, body = kk.http_get("https://kisskh.asia/x", retries=2)
        self.assertEqual(status, 0)
        self.assertIn("network error", body)

    def test_http_get_once_leaves_the_redirect_in_the_headers(self):
        resp = FakeResponse("", status=302, headers={"Location": "https://cdn.example/file.mp4"})
        with mock.patch.object(kk._NO_REDIRECT_OPENER, "open", return_value=resp) as opened:
            status, location, _ = kk.http_get_once("https://kisskh.asia/download/1")
        self.assertEqual((status, location), (302, "https://cdn.example/file.mp4"))
        self.assertNotIn("Referer", opened.call_args[0][0].headers)

    def test_a_probe_can_be_sent_with_the_site_referer(self):
        with mock.patch.object(kk._NO_REDIRECT_OPENER, "open",
                               return_value=FakeResponse("ok")) as opened:
            status, location, body = kk.http_get_once("https://hlscdn.vip/a.mp4",
                                                      referer="https://kisskh.asia/x/")
        self.assertEqual((status, location, body), (200, None, "ok"))
        self.assertEqual(opened.call_args[0][0].get_header("Referer"), "https://kisskh.asia/x/")

    def test_an_error_response_still_reports_its_location(self):
        err = http_error(403, "denied", headers={"Location": "https://gate.example/challenge"})
        with mock.patch.object(kk._NO_REDIRECT_OPENER, "open", side_effect=err):
            status, location, body = kk.http_get_once("https://hlscdn.vip/a.mp4")
        self.assertEqual((status, location, body), (403, "https://gate.example/challenge", "denied"))

    def test_a_response_object_without_headers_is_not_a_crash(self):
        with mock.patch.object(kk._NO_REDIRECT_OPENER, "open",
                               return_value=FakeResponse("ok", headers=None)):
            self.assertEqual(kk.http_get_once("https://x/a.mp4")[0], 200)

    def test_an_error_body_that_cannot_be_read_is_described(self):
        with mock.patch.object(kk._NO_REDIRECT_OPENER, "open",
                               side_effect=http_error(500, readable=False)):
            status, _, body = kk.http_get_once("https://x/a.mp4")
        self.assertEqual(status, 500)
        self.assertTrue(body.startswith("[unreadable error body]"))

    def test_a_socket_failure_once_is_zero_and_no_location(self):
        with mock.patch.object(kk._NO_REDIRECT_OPENER, "open", side_effect=OSError("reset")):
            self.assertEqual(kk.http_get_once("https://x/a.mp4"),
                             (0, None, "[network error] reset"))

    def test_the_stop_redirect_handler_refuses_to_follow(self):
        handler = kk._StopRedirect()
        self.assertIsNone(handler.redirect_request(None, None, 302, "Found", {},
                                                  "https://elsewhere.example/x"))

    def test_the_openers_are_built_once_and_are_rebuildable(self):
        context = kk._build_ssl_context()
        following, non_following = kk._build_openers(context)
        self.assertEqual(following.addheaders[0], ("User-Agent", kk.USER_AGENT))
        self.assertTrue(any(isinstance(h, kk._StopRedirect) for h in non_following.handlers))
        self.assertFalse(any(isinstance(h, kk._StopRedirect) for h in following.handlers))


class TestSignalsAndCLI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = Path(self.tmp) / "kisskh.db"

    def tearDown(self):
        kk.STOP_REQUESTED = False

    def test_the_stop_handler_asks_the_driver_to_drain(self):
        with silenced() as out:
            kk._signal_handler(signal.SIGINT, None)
        self.assertTrue(kk.STOP_REQUESTED)
        self.assertIn("received; draining in-flight pages", out.getvalue())

    def test_signals_can_only_be_installed_from_the_main_thread(self):
        outcome = {}

        def in_thread():
            outcome["installed"] = kk._install_signal_handlers()

        thread = threading.Thread(target=in_thread)
        thread.start()
        thread.join()
        self.assertFalse(outcome["installed"])
        self.assertTrue(kk._install_signal_handlers())

    def test_sync_from_the_command_line(self):
        with mock.patch.object(kk, "iter_catalog_posts",
                               return_value=iter([wp_record(pid=1)])):
            self.assertEqual(kk.main(["sync", "--db", str(self.db), "--quiet"]), 0)

    def test_crawl_from_the_command_line(self):
        with mock.patch.object(kk, "iter_catalog_posts",
                               return_value=iter([wp_record(pid=1)])):
            kk.sync_catalog(db_path=self.db, verbose=False)
        with mock.patch.object(kk, "http_get", return_value=(200, "", json.dumps(
                {"html": blob(eps=("1",))}))), \
                mock.patch.object(kk, "http_get_once",
                                  return_value=(200, "https://cdn.example/e1.mp4", "")):
            self.assertEqual(kk.main(["crawl", "--db", str(self.db), "--workers", "1",
                                      "--delay", "0", "--probe", "--deep", "--quiet"]), 0)

    def test_stats_from_the_command_line_prints_json(self):
        kk.export_staging(self.db, [])
        with mock.patch.object(sys, "stdout", new_callable=io.StringIO) as out:
            self.assertEqual(kk.main(["stats", "--db", str(self.db)]), 0)
        self.assertIn("subtitle_tracks", json.loads(out.getvalue()))

    def test_parse_and_resolve_from_the_command_line(self):
        record = wp_record(pid=9)
        with mock.patch.object(kk, "_fetch_post_by_slug", return_value=record), \
                mock.patch.object(kk, "http_get", return_value=(200, "", json.dumps(
                    {"html": blob(eps=("1",))}))), \
                mock.patch.object(kk, "http_get_once",
                                  return_value=(200, "https://cdn.example/e1.mp4", "")):
            with mock.patch.object(sys, "stdout", new_callable=io.StringIO) as out:
                self.assertEqual(kk.main(["resolve", "--db", str(self.db), "--url",
                                          record["link"], "--deep"]), 0)
        self.assertIn("releases", json.loads(out.getvalue()))

    def test_parse_refuses_a_url_that_is_not_a_drama(self):
        with mock.patch.object(kk, "_fetch_post_by_slug", return_value=None), \
                silenced() as out:
            self.assertEqual(kk.main(["parse", "--db", str(self.db), "--url",
                                      "https://kisskh.asia/explore/"]), 1)
        self.assertIn("Page is not a catalog entry.", out.getvalue())

    def test_parse_without_a_url_is_a_usage_error(self):
        with silenced() as out:
            with self.assertRaises(SystemExit) as stop:
                kk.main(["parse", "--db", str(self.db)])
        self.assertEqual(stop.exception.code, 2)
        self.assertIn("parse requires --url", out.getvalue())

    def test_argv_defaults_to_the_real_command_line(self):
        with mock.patch.object(sys, "argv", ["import_kisskh.py", "stats", "--db", str(self.db)]), \
                mock.patch.object(sys, "stdout", new_callable=io.StringIO):
            self.assertEqual(kk.main(), 0)

    def test_the_module_runs_as_a_script(self):
        kk.export_staging(self.db, [])
        argv = ["import_kisskh.py", "stats", "--db", str(self.db)]
        with mock.patch.object(sys, "argv", argv), \
                mock.patch.object(sys, "stdout", new_callable=io.StringIO):
            with self.assertRaises(SystemExit) as stop:
                import runpy
                runpy.run_module("import_kisskh", run_name="__main__")
        self.assertEqual(stop.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
