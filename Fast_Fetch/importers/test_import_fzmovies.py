#!/usr/bin/env python3
"""
test_import_fzmovies.py — offline unit tests for the fzmovies.host importer.

No network, no production file: every case feeds a captured page shape into the
parser and writes into a throwaway staging database under a temp directory.

The fixtures are transcriptions of two real pages fetched once each on
2026-10-30 (`/` and one item page), reduced to the structures that carry
meaning. They exist to pin the things a first reading of this site gets wrong:

  * the release anchor's real `href` has no `pt=` token; the token is inside
    `onclick='window.location.href="…&pt=…"'`. A plain `href=` search finds the
    JS copy first and would store visitor state as the link.
  * the file size and the site's own hit count are OUTSIDE the anchor, in a
    `<dcounter>` block, so an anchor-text-only reader stores sizeless releases.
  * the site repeats its year inside `itemprop='name'`, so naive keying yields
    `the-break-up-2006-2006` and never joins the same work from another site.
  * the dubbed rail names its items `movie--Dubbed--<Title> [Hindi].htm` — no
    `--hmp4` tail at all — while `movie-…--subtitle.htm` is the same shape and
    is not a work.
  * the page is not JSON-LD and has no `og:*`, but it is full schema.org Movie
    microdata, which is where imdb_id, synopsis, cast, director and runtime come
    from.
"""

from __future__ import annotations

import re
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import import_fzmovies as fz  # noqa: E402

HOME_PAGE = """<!DOCTYPE html><html><head><title>FzMovies - Bollywood and Hollywood</title></head>
<body><div class='links'>
<a href='/index.php'></a>
<a href='advancedsearch.php'>(Advanced Search)</a>
<a href='http://www.mobiletvshows.site'>MobileTVshows - TV shows</a>
<a href='contact.php'>Contact Us</a>
<a href='mquality.php'>Quality Types</a>
</div>
<div class='rail'><a href='movieslist.php?catID=2&by=latest'>Hollywood Movies</a>
<a href='hotmovies.php?catID=2'>What are people watching right now?</a>
<a href='movieslist.php?catID=2&by=downloads'>By Most Downloaded</a>
<a href='genre.php?catID=2'>Genres</a>
<a href='alpha.php?catID=2'>By Alpha</a>
<a href='movie-The%20Break-Up%202006--hmp4.htm'>The Break-Up 2006</a>
<a href='movie-Blue%20Heron--hmp4.htm'>Blue Heron</a>
<a href='movie-Skyline%202010--hmp4.htm'>Skyline 2010</a>
<a href='movie-Mr.%20and%20Mrs.%20Christmas%202026--hmp4.htm'>Mr. and Mrs. Christmas 2026</a>
<a href='movieslist.php?catID=1&by=latest'>Bollywood Movies</a>
<a href='movie-Lust%20Stories%203%202026--hmp4.htm'>Lust Stories 3 2026</a>
<a href='movie-Lust%20Stories%203%202026--hmp4.htm'>Lust Stories 3 2026</a>
<a href='movie-Dhamaal%204--hmp4.htm'>Dhamaal 4</a>
<a href='movieslist.php?catID=3&by=latest'>Hollywood Dubbed Movies</a>
<a href='movie--Dubbed--The Tiger Rising [Hindi].htm'>The Tiger Rising [Hindi]</a>
<a href='movie--Dubbed--The Monkey is Back [Hindi].htm'>The Monkey is Back [Hindi]</a>
</div></body></html>"""

# One item page, transcribed. Every attribute quirk below is present in the
# captured bytes, including the single quotes inside an unquoted-looking script.
ITEM_PAGE = """<!DOCTYPE html><html><head>
<title>The Break-Up 2006 (2006)</title>
<script src='https://cdnjs.cloudflare.com/ajax/libs/font-awesome/4.7.0/css/font-awesome.min.css'>
</script></head><body>
<div class='nav'><a href='movieslist.php?catID=2&by=latest'>Hollywood Movies</a></div>
<div itemscope itemtype='http://schema.org/Movie'>
<div class='moviename'><span itemprop='name'>The Break-Up 2006</span> <dcounter>(in
<a href='movieslist.php?catID=2&by=latest'>Hollywood Movies</a>)</dcounter><br>
The Break-Up 2006 (2006) - Download Movie for mobile in best quality 3gp and mp4 format</div>
<div class='moviedesc'><span><img itemprop='image' src="/imdb_images/The.Break-Up.2006.jpg"
 width='214' height='317'></img></span><br>
Plot: <span><textcolor1 itemprop='description'>A couple's break-up proceeds to get uglier and
nastier by the moment as each tries to keep their luxurious condo from the other.</textcolor1>
</span><br>Runtime: <textcolor2>1h 46m</textcolor2><br>
Release Date: <textcolor1>02 Jun <a href='year.php?catID=2&year=2006'>2006</a></textcolor1><br>
<meta itemprop='datePublished' content='2006-06-02'><meta itemprop='dateModified' content='2026-10-29'>
<div itemprop='actor' itemscope itemtype='http://schema.org/Person'><meta itemprop='name'
 content='Jennifer Aniston'><meta itemprop='name' content='Vince Vaughn'><meta itemprop='name'
 content='Jon Favreau'></div>Starcast:
<a href='starcast.php?catID=2&starcast=Jennifer%20Aniston'>Jennifer Aniston</a><br>
<div itemprop='director' itemscope itemtype='http://schema.org/Person'><meta itemprop='name'
 content='Peyton Reed'></div>Director(s):
<a href='director.php?catID=2&director=Peyton%20Reed'>Peyton Reed</a><br>
Genre: <textcolor1><a href='genre.php?catID=2&genre=Comedy'><span itemprop='genre'>Comedy</span></a>,
<a href='genre.php?catID=2&genre=Drama'><span itemprop='genre'>Drama</span></a>,
<a href='genre.php?catID=2&genre=Romance'><span itemprop='genre'>Romance</span></a>, </textcolor1><br>
Tags: <textcolor1><a href='movietags.php?tag=neo screwball comedy'><span itemprop='tag'
>neo screwball comedy</span></a>, <a href='movietags.php?tag=art'><span itemprop='tag'>art</span>
</a></textcolor1><br>
IMDb: <textcolor2><span itemprop='sameAs'>http://www.imdb.com/title/tt0452594/</span></textcolor2><br>
Downloads: <textcolor1>41621.5</textcolor1><br>
IMDb Rating: <textcolor11>5.8</textcolor11><textcolor111>/10 (148862 votes)</textcolor111><br>
<div class='downloads'><div>Download Links <a href='movie-The Break-Up 2006--hmp4.htm'>480p and 720p</a>
&nbsp; Subtitles &nbsp;&nbsp;-&nbsp;&nbsp; <a href='movie-The Break-Up 2006--subtitle.htm'>Subtitles</a>
</div><br>
<a onclick='window.location.href="download1.php?downloadoptionskey=3-10504-6de26004dc761253989a2b901dfbe69e&pt=jRGarGzOo2"; return false;'
 itemprop='url' href='download1.php?downloadoptionskey=3-10504-6de26004dc761253989a2b901dfbe69e'
>The Break-Up 2006 BluRay 480p.mp4</a> <br><dcounter> (284 MB) { 34466 hits }</dcounter> -
<a onclick='window.open("https://www.googletagmanager.com/gtag/js")'>MediaInfo</a>
<a href='mediainfo.php?downloadoptionskey=3-10504-6de26004dc761253989a2b901dfbe69e'>MediaInfo</a>
<a href='ss.php?downloadoptionskey=3-10504-6de26004dc761253989a2b901dfbe69e'>SS</a><br><br>
<a onclick='window.location.href="download1.php?downloadoptionskey=5-34566-c393951e784e57bdc88d2a7123ca1e02&pt=jRGarGzOo2"; return false;'
 itemprop='url' href='download1.php?downloadoptionskey=5-34566-c393951e784e57bdc88d2a7123ca1e02'
>The Break-Up 2006 BluRay 720p.mkv</a><br> <dcounter> (673 MB) { 6547 hits }</dcounter> -
<a href='mediainfo.php?downloadoptionskey=5-34566-c393951e784e57bdc88d2a7123ca1e02'>MediaInfo</a>
</div>
<iframe width='560' height='315' src='https://www.youtube.com/embed/SfTaJUh3_J4'></iframe>
<a href='reviews.php?movie=The Break-Up 2006'>Write a review</a>
<div class='sidebar'><a href='movie-Get Out--hmp4.htm'><img src='/imdb_images/Get.Out.2017.jpg'
 height = 200></a></div>
</div></body></html>"""


class AnchorParsingTests(unittest.TestCase):
    """The trap this site sets: a JS string that looks exactly like an href."""

    def test_real_href_wins_over_the_one_inside_onclick(self):
        records = [r for r in fz.anchor_records(ITEM_PAGE) if fz.download_key(r["href"])]
        self.assertEqual(len(records), 2)
        for rec in records:
            self.assertNotIn("pt=", rec["href"], "the visitor token leaked into the parsed href")
            self.assertIn("window.location.href", rec["attrs"].get("onclick", ""))
            self.assertIn("pt=", rec["attrs"]["onclick"],
                          "the token lives in the script, where it belongs")

    def test_anchor_attrs_take_the_first_spelling_of_a_name(self):
        attrs = fz.anchor_attrs("""onclick='window.location.href="js.example/x"' href='real.php'""")
        self.assertEqual(attrs["href"], "real.php")
        self.assertEqual(list(attrs)[0], "onclick")

    def test_anchor_attrs_unescape_entities(self):
        attrs = fz.anchor_attrs("""href='a.php?k=1&amp;pt=2'""")
        self.assertEqual(attrs["href"], "a.php?k=1&pt=2")

    def test_records_expose_inner_text_and_end_offset(self):
        rec = next(r for r in fz.anchor_records("<a href='x.htm'>Hello <b>World</b></a>tail"))
        self.assertEqual(fz.clean_text(rec["inner"]), "Hello World")
        self.assertGreater(rec["end"], 0)


class DownloadKeyTests(unittest.TestCase):

    def test_relative_and_absolute_forms_give_the_same_key(self):
        key = "3-10504-6de26004dc761253989a2b901dfbe69e"
        for href in (f"download1.php?downloadoptionskey={key}",
                     f"https://fzmovies.host/download1.php?downloadoptionskey={key}",
                     f"./download1.php?downloadoptionskey={key}",
                     f"download1.php?downloadoptionskey={key}&pt=jRGarGzOo2"):
            self.assertEqual(fz.download_key(href), key, href)

    def test_other_pages_that_share_the_key_are_not_downloads(self):
        key = "3-10504-6de26004dc761253989a2b901dfbe69e"
        for href in (f"mediainfo.php?downloadoptionskey={key}",
                     f"ss.php?downloadoptionskey={key}",
                     "download1.php?downloadoptionskey=not-a-key",
                     "download2.php?downloadoptionskey=3-10504-abc",
                     "download1.php?downloadoptionskey=3-10504-6de&pt=x#frag"):
            if href.startswith("download1.php?downloadoptionskey=3-10504-6de"):
                self.assertEqual(fz.download_key(href), "3-10504-6de")
            else:
                self.assertIsNone(fz.download_key(href), href)

    def test_malformed_keys_are_rejected(self):
        for href in ("download1.php", "download1.php?downloadoptionskey=",
                     "download1.php?downloadoptionskey=3-10504-xyz",
                     "download1.php?downloadoptionskey=3-10504-6de26004dc761253989a2b901dfbe69eZ"):
            self.assertIsNone(fz.download_key(href), href)

    def test_stored_url_carries_no_visitor_token(self):
        result = fz.parse_item(ITEM_PAGE, "https://fzmovies.host/movie-The%20Break-Up%202006--hmp4.htm")
        for src in result["sources"]:
            self.assertNotIn("pt=", src["source_url"])
            self.assertTrue(src["source_url"].startswith("https://fzmovies.host/download1.php?downloadoptionskey="))


class ListingTests(unittest.TestCase):

    def setUp(self):
        self.items = fz.parse_listing(HOME_PAGE)
        self.paths = [item["path"] for item in self.items]

    def test_every_item_link_on_the_homepage_is_found(self):
        self.assertEqual(len(self.items), 8, self.paths)

    def test_rail_and_nav_links_are_not_items(self):
        for path in self.paths:
            self.assertTrue(path.startswith("movie-"), path)
        for junk in ("movieslist.php", "alpha.php", "genre.php", "advancedsearch.php",
                     "http://www.mobiletvshows.site"):
            self.assertFalse(any(junk in p for p in self.paths), junk)

    def test_dubbed_items_without_the_hmp4_tail_are_still_items(self):
        self.assertIn("movie--Dubbed--The Tiger Rising [Hindi].htm", self.paths)
        dubbed = next(i for i in self.items if i["dubbed"])
        self.assertEqual(dubbed["title_from_href"], "The Tiger Rising")
        self.assertEqual(dubbed["langs"], ["Hindi"])
        self.assertIsNone(dubbed["year"])

    def test_a_subtitle_link_is_never_an_item(self):
        page = "<a href='movie-The Break-Up 2006--subtitle.htm'>Subtitles</a>"
        self.assertEqual(fz.parse_listing(page), [])

    def test_the_same_title_listed_twice_is_returned_once(self):
        self.assertEqual(self.paths.count("movie-Lust%20Stories%203%202026--hmp4.htm"), 1)

    def test_link_text_is_preferred_over_the_href_derived_title(self):
        item = next(i for i in self.items if i["path"].startswith("movie-Mr."))
        self.assertEqual(item["title"], "Mr. and Mrs. Christmas 2026")
        self.assertEqual(item["title_from_href"], "Mr. and Mrs. Christmas")
        self.assertEqual(item["year"], 2026)

    def test_titles_without_a_year_keep_a_null_year_rather_than_a_guess(self):
        item = next(i for i in self.items if "Blue" in i["path"])
        self.assertIsNone(item["year"])

    def test_rail_names_are_read_off_the_page_not_hardcoded(self):
        self.assertEqual(fz.parse_rail_names(HOME_PAGE),
                         {"2": "hollywood", "1": "bollywood", "3": "dubbed"})


class TitleFromHrefTests(unittest.TestCase):

    def test_percent_encoded_title_with_year(self):
        self.assertEqual(fz.title_from_href("movie-The%20Break-Up%202006--hmp4.htm"),
                         ("The Break-Up", 2006))

    def test_literal_spaces_inside_the_filename(self):
        self.assertEqual(fz.title_from_href("movie-The Break-Up 2006--hmp4.htm"),
                         ("The Break-Up", 2006))

    def test_no_year_no_tail(self):
        self.assertEqual(fz.title_from_href("movie-Blue%20Heron--hmp4.htm"), ("Blue Heron", None))

    def test_a_four_digit_tail_below_1900_is_not_a_year(self):
        self.assertEqual(fz.title_from_href("movie-Ocean%201440--hmp4.htm"), ("Ocean 1440", None))

    def test_dubbed_shape_drops_the_rail_prefix_and_the_language_bracket(self):
        self.assertEqual(fz.title_from_href("movie--Dubbed--The Tiger Rising [Hindi].htm"),
                         ("The Tiger Rising", None))

    def test_dotted_trailing_junk_is_trimmed(self):
        self.assertEqual(fz.title_from_href("movie-Top.Gun..--hmp4.htm"), ("Top.Gun", None))


class MicrodataTests(unittest.TestCase):

    def setUp(self):
        self.micro = fz.parse_microdata(ITEM_PAGE)

    def test_the_movie_block_fields_are_all_present(self):
        self.assertEqual(self.micro["name"], "The Break-Up 2006")
        self.assertTrue(self.micro["description"].startswith("A couple's break-up"))
        self.assertEqual(self.micro["image"], "/imdb_images/The.Break-Up.2006.jpg")
        self.assertEqual(self.micro["genres"], ["Comedy", "Drama", "Romance"])
        self.assertEqual(self.micro["tags"], ["neo screwball comedy", "art"])
        self.assertEqual(self.micro["sameas"], "http://www.imdb.com/title/tt0452594/")
        self.assertEqual(self.micro["datepublished"], "2006-06-02")
        self.assertEqual(self.micro["datemodified"], "2026-10-29")

    def test_people_come_from_the_nested_person_blocks(self):
        self.assertEqual(self.micro["cast"], ["Jennifer Aniston", "Vince Vaughn", "Jon Favreau"])
        self.assertEqual(self.micro["director"], ["Peyton Reed"])

    def test_the_plain_text_counters_are_read_too(self):
        self.assertEqual(self.micro["runtime"], "1h 46m")
        self.assertEqual(self.micro["imdb_rating"], "5.8")
        self.assertEqual(self.micro["imdb_votes"], "148862")
        self.assertEqual(self.micro["download_count"], "41621.5")

    def test_a_page_with_no_microdata_yields_empty_buckets_not_an_error(self):
        micro = fz.parse_microdata("<html><body><p>nothing here</p></body></html>")
        self.assertEqual(micro["genres"], [])
        self.assertEqual(micro["cast"], [])
        self.assertNotIn("description", micro)


class ReleaseLabelTests(unittest.TestCase):

    def test_quality_container_source_and_label(self):
        rel = fz.parse_item_release("The Break-Up 2006 BluRay 720p.mkv")
        self.assertEqual(rel["quality"], "720p")
        self.assertEqual(rel["container"], "mkv")
        self.assertEqual(rel["source"], "BluRay")
        self.assertIsNone(rel["size_bytes"])

    def test_size_inside_the_label_is_parsed_when_present(self):
        rel = fz.parse_item_release("Jawan 2023 1080p WEB-DL 3.5 GB")
        self.assertEqual(rel["quality"], "1080p")
        self.assertEqual(rel["container"], None)
        self.assertEqual(rel["size_bytes"], int(3.5 * 1024**3))

    def test_a_label_with_no_quality_is_still_kept_as_evidence(self):
        rel = fz.parse_item_release("Some Files")
        self.assertIsNone(rel["quality"])
        self.assertEqual(rel["label"], "Some Files")


class ReleaseCounterTests(unittest.TestCase):

    def test_each_release_gets_its_own_size_and_hits(self):
        result = fz.parse_item(ITEM_PAGE, "https://fzmovies.host/movie-The%20Break-Up%202006--hmp4.htm")
        sizes = [rel["size_bytes"] for rel in result["releases"]]
        hits = [rel["hits"] for rel in result["releases"]]
        self.assertEqual(sizes, [284 * 1024**2, 673 * 1024**2])
        self.assertEqual(hits, [34466, 6547])

    def test_a_release_inherits_only_the_counter_that_follows_it(self):
        page = ("<a href='download1.php?downloadoptionskey=9-9-abc'>Film 2024 720p.mp4</a>"
                "<a href='download1.php?downloadoptionskey=8-8-def'>Film 2024 480p.mp4</a>"
                "<dcounter> (100 MB) { 5 hits }</dcounter>")
        result = fz.parse_item(page, "https://fzmovies.host/movie-Film%202024--hmp4.htm")
        self.assertEqual([r["size_bytes"] for r in result["releases"]], [None, 100 * 1024**2])
        self.assertEqual([r["hits"] for r in result["releases"]], [None, 5])

    def test_a_malformed_counter_is_ignored_not_guessed(self):
        self.assertEqual(fz.release_counters("<dcounter> (big) { many }</dcounter>", 0, 40),
                         (None, None))


class ParseItemTests(unittest.TestCase):

    def setUp(self):
        self.url = "https://fzmovies.host/movie-The%20Break-Up%202006--hmp4.htm"
        self.result = fz.parse_item(ITEM_PAGE, self.url)
        self.post = self.result["post"]

    def test_the_year_the_site_repeats_in_its_title_is_not_keyed_twice(self):
        self.assertEqual(self.post["clean_title"], "The Break-Up")
        self.assertEqual(self.post["year"], 2006)
        self.assertEqual(self.post["canonical_key"], "the-break-up-2006")

    def test_the_join_key_the_rest_of_the_catalog_uses_is_captured(self):
        self.assertEqual(self.post["imdb_id"], "tt0452594")
        self.assertEqual(self.post["imdb_rating"], "5.8")

    def test_metadata_lands_in_real_columns(self):
        self.assertEqual(self.post["director"], "Peyton Reed")
        self.assertEqual(self.post["cast_names"], "Jennifer Aniston, Vince Vaughn, Jon Favreau")
        self.assertEqual(self.post["duration"], "1h 46m")
        self.assertEqual(self.post["release_date"], "2006-06-02")
        self.assertEqual(self.post["industry"], "hollywood")
        self.assertEqual(self.post["poster_url"],
                         "https://fzmovies.host/imdb_images/The.Break-Up.2006.jpg")
        self.assertEqual(self.post["trailer_youtube_id"], "SfTaJUh3_J4")
        self.assertEqual(self.post["media_type"], "movie")

    def test_genres_and_languages_are_stored_as_json_text(self):
        self.assertEqual(self.post["genres"], '["Comedy", "Drama", "Romance"]')
        self.assertEqual(self.post["languages"], "[]")

    def test_the_grouping_anchor_is_not_a_release(self):
        labels = [rel["label"] for rel in self.result["releases"]]
        self.assertEqual(len(labels), 2, labels)
        self.assertFalse(any("and" == label.lower() for label in labels))

    def test_a_sibling_sidebar_item_is_not_mistaken_for_a_release(self):
        for src in self.result["sources"]:
            self.assertIn("downloadoptionskey", src["source_url"])
            self.assertNotIn("Get.Out", src["source_url"])

    def test_every_source_is_unverified_redirect_evidence_never_a_watchable_link(self):
        for src in self.result["sources"]:
            self.assertEqual(src["playback_type"], "redirect")
            self.assertEqual(src["status"], "unverified")
            self.assertEqual(src["is_temporary"], 1)
            self.assertIsNone(src["final_url"])
            self.assertEqual(src["source_name"], "fzmovies")

    def test_a_page_with_nothing_to_key_on_is_refused_not_stored_as_noise(self):
        self.assertIsNone(fz.parse_item("<html><body><p>Server busy</p></body></html>",
                                        "https://fzmovies.host/index.php"))
        self.assertIsNone(fz.parse_item("<a href='x'> </a>", "https://fzmovies.host/"))

    def test_a_rail_or_subtitle_url_is_refused_even_when_it_carries_a_title(self):
        page = "<title>Movies (2026)</title><p>list</p>"
        for url in ("https://fzmovies.host/movieslist.php?catID=2",
                    "https://fzmovies.host/alpha.php",
                    "https://fzmovies.host/movie-The%20Break-Up%202006--subtitle.htm"):
            self.assertIsNone(fz.parse_item(page, url), url)

    def test_adult_flagging_errs_toward_the_flag(self):
        page = ITEM_PAGE.replace("<title>The Break-Up 2006 (2006)</title>",
                                 "<title>Kali Aunty 18+ (2026)</title>") \
                        .replace("<span itemprop='name'>The Break-Up 2006</span>",
                                 "<span itemprop='name'>Kali Aunty 18+</span>")
        result = fz.parse_item(page, "https://fzmovies.host/movie-Kali%20Aunty%2018%2B--hmp4.htm")
        self.assertEqual(result["post"]["is_18_plus"], 1)

    def test_a_strong_token_anywhere_on_the_page_flags_the_row(self):
        page = ITEM_PAGE.replace("BluRay 480p.mp4", "18+ Uncut 480p.mp4")
        result = fz.parse_item(page, "https://fzmovies.host/movie-The%20Break-Up%202006--hmp4.htm")
        self.assertEqual(result["post"]["is_18_plus"], 1)

    def test_no_adult_keyword_is_a_bare_version_word(self):
        """`test_database.py` enforces this fleet-wide: a cut-version word flags
        nothing on its own, because it decorates mainstream releases too. Asserted
        here so this lane sees the rule before the CI step names another file."""
        banned = {"uncut", "unrated", "extended", "remastered", "remaster",
                  "restored", "imax", "theatrical", "fanedit", "fansub", "cut"}
        for keyword in fz.ADULT_KEYWORDS:
            self.assertFalse(banned & set(re.findall(r"[a-z]+", keyword.lower())),
                             f"{keyword!r} is a version word, not an adult signal")

    def test_a_version_word_alone_does_not_flag_a_mainstream_title(self):
        for title in ("Kanguva Uncut", "Inception Extended", "Dune Part Two Remastered"):
            self.assertEqual(fz.looks_adult(title), 0, title)

    def test_looks_adult_is_zero_for_an_ordinary_title(self):
        self.assertEqual(fz.looks_adult("The Break-Up"), 0)
        self.assertEqual(fz.looks_adult("Palang Tod Ullu series"), 1)
        self.assertEqual(fz.looks_adult(None, "", "Some Film 4K Bedroom Affair"), 1)

    def test_version_words_over_a_mainstream_work_stay_unflagged(self):
        """The other half of the law: a version word stacked on a version word is
        still only a version word. `test_a_version_word_alone_...` refuses one; this
        refuses the pair that an `uncut|unrated` regex used to catch — and used to
        hide mainstream releases behind an adult flag no public surface could undo."""
        self.assertEqual(fz.looks_adult(None, "", "Some Film 4K UNRATED uncUT"), 0)


class SchemaWriteTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.conn = sqlite3.connect(Path(self.tmp.name) / "fzmovies.db")
        self.addCleanup(self.conn.close)
        fz.ensure_schema(self.conn)

    def _columns(self, table):
        return [row[1] for row in self.conn.execute(f"PRAGMA table_info({table})")]

    def test_the_ddl_executes_on_a_real_database(self):
        for table in ("page_cache", "posts", "releases", "sources"):
            self.assertIn(table, [r[0] for r in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")])

    def test_the_column_tuples_match_the_ddl_exactly(self):
        """Guards the drift that makes an INSERT fail only on the first real run."""
        posts = [c for c in self._columns("posts") if c != "scraped_at"]
        self.assertEqual(list(fz.POST_COLUMNS), posts,
                         "posts: POST_COLUMNS drifted from the DDL (scraped_at is a DDL default)")
        self.assertEqual(list(fz.RELEASE_COLUMNS), self._columns("releases")[1:],
                         "releases: RELEASE_COLUMNS drifted from the DDL")
        self.assertEqual(list(fz.SOURCE_COLUMNS), self._columns("sources")[1:],
                         "sources: SOURCE_COLUMNS drifted from the DDL")

    def test_every_declared_extra_key_reaches_raw_meta_rather_than_the_bin(self):
        for key in fz.EXTRA_POST_KEYS:
            self.assertIn(key, self.post_keys())

    def post_keys(self):
        result = fz.parse_item(ITEM_PAGE, "https://fzmovies.host/movie-The%20Break-Up%202006--hmp4.htm")
        fz.write_result(self.conn, result)
        import json as _json
        return _json.loads(self.conn.execute("SELECT raw_meta FROM posts").fetchone()[0])

    def test_one_item_writes_one_post_and_one_row_per_release_and_source(self):
        result = fz.parse_item(ITEM_PAGE, "https://fzmovies.host/movie-The%20Break-Up%202006--hmp4.htm")
        self.assertEqual(fz.write_result(self.conn, result), 2)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0], 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM releases").fetchone()[0], 2)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0], 2)
        self.assertEqual(
            self.conn.execute("SELECT size_bytes, container, source_tag, site_hits "
                              "FROM releases ORDER BY id").fetchall(),
            [(284 * 1024**2, "mp4", "BluRay", 34466), (673 * 1024**2, "mkv", "BluRay", 6547)])

    def test_re_running_the_same_page_stores_nothing_twice(self):
        result = fz.parse_item(ITEM_PAGE, "https://fzmovies.host/movie-The%20Break-Up%202006--hmp4.htm")
        fz.write_result(self.conn, result)
        self.assertEqual(fz.write_result(self.conn, dict(result)), 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM releases").fetchone()[0], 2)

    def test_each_source_row_points_at_its_own_release(self):
        result = fz.parse_item(ITEM_PAGE, "https://fzmovies.host/movie-The%20Break-Up%202006--hmp4.htm")
        fz.write_result(self.conn, result)
        rows = self.conn.execute(
            "SELECT r.quality, s.quality, s.resource_id FROM releases r "
            "JOIN sources s ON s.release_id = r.id ORDER BY r.id").fetchall()
        self.assertEqual([r[0] for r in rows], [r[1] for r in rows])
        self.assertEqual([r[0] for r in rows], ["480p", "720p"])

    def test_the_importer_never_names_the_production_catalog(self):
        """The per-site staging rule, asserted rather than promised."""
        self.assertTrue(str(fz.DEFAULT_DB_PATH).endswith("fzmovies.db"))
        self.assertNotIn("fast_fetch", str(fz.DEFAULT_DB_PATH))
        self.assertNotIn("merged_catalog", str(fz.DEFAULT_DB_PATH))
        with open(Path(__file__).resolve().parent / "import_fzmovies.py", encoding="utf-8") as fh:
            source = fh.read()
        self.assertNotIn("merge_catalogs", source.replace("`merge_catalogs.py`", ""))


class CrawlGateTests(unittest.TestCase):
    """The owner's fleet rule as code: a crawl is refused, not discouraged."""

    def test_a_quiet_machine_with_a_bound_opens_the_gate(self):
        self.assertEqual(fz.crawl_blocked(1.2, 5200.0, 0, 50), [])

    def test_load_at_or_above_the_ceiling_blocks(self):
        self.assertEqual(fz.crawl_blocked(fz.LOAD_CEILING, 5200.0, 0, 50),
                         ["1-min load 4.00 is at or above the 4.0 ceiling"])
        self.assertTrue(fz.crawl_blocked(6.92, 5200.0, 0, 50))

    def test_memory_at_or_below_the_floor_blocks(self):
        reasons = fz.crawl_blocked(1.0, 3999.0, 0, 50)
        self.assertIn("MemAvailable 3999 MB is at or below 4000 MB", reasons)

    def test_another_lane_crawling_blocks(self):
        self.assertEqual(fz.crawl_blocked(1.0, 8000.0, 2, 50),
                         ["2 other import process(es) are running"])

    def test_an_unbounded_crawl_is_never_the_default(self):
        for limit in (None, 0, -5):
            self.assertIn("no --limit given; an unbounded crawl is never started by default",
                          fz.crawl_blocked(1.0, 8000.0, 0, limit), repr(limit))

    def test_all_three_bad_conditions_report_all_three(self):
        reasons = fz.crawl_blocked(9.0, 800.0, 1, None)
        self.assertEqual(len(reasons), 4, reasons)

    def test_load_and_memory_are_read_from_proc_not_assumed(self):
        self.assertGreaterEqual(fz.read_loadavg("/proc/loadavg"), 0.0)
        self.assertGreater(fz.read_mem_available_mb("/proc/meminfo"), 0.0)
        self.assertEqual(fz.read_loadavg("/proc/definitely-not-here"), 9999.0)
        self.assertEqual(fz.read_mem_available_mb("/proc/definitely-not-here"), 0.0)

    def test_sync_refuses_and_writes_nothing_when_the_gate_is_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "fzmovies.db"
            with mock.patch.object(fz, "current_gate_state",
                                   return_value=(7.5, 5200.0, 0)) as gate, \
                 mock.patch.object(fz, "http_get", side_effect=AssertionError("crawled anyway")):
                rc = fz.sync(db, limit=50, delay=0, rails=[("hollywood", "movieslist.php?catID=2")],
                             quiet=True)
            self.assertEqual(rc, 3)
            gate.assert_called_once()
            self.assertFalse(db.exists(), "a blocked crawl must not even create the staging file")

    def test_sync_runs_boundedly_once_the_gate_is_open(self):
        page = HOME_PAGE
        item = ITEM_PAGE
        url = "https://fzmovies.host/movie-The%20Break-Up%202006--hmp4.htm"

        def fake_get(requested, **_kw):
            return 200, item if requested == url else page

        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "fzmovies.db"
            with mock.patch.object(fz, "current_gate_state", return_value=(0.4, 6000.0, 0)), \
                 mock.patch.object(fz, "http_get", side_effect=fake_get), \
                 mock.patch.object(fz.time, "sleep"):
                rc = fz.sync(db, limit=1, delay=0,
                             rails=[("hollywood", "movieslist.php?catID=2&by=latest")], quiet=True)
            self.assertEqual(rc, 0)
            conn = sqlite3.connect(db)
            try:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0], 1)
                self.assertEqual(conn.execute("SELECT url FROM page_cache").fetchone()[0], url)
            finally:
                conn.close()

    def test_a_rate_limited_rail_ends_the_run_instead_of_pushing_through(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "fzmovies.db"
            seen: list[str] = []

            def fake_get(requested, **_kw):
                seen.append(requested)
                return 429, ""

            with mock.patch.object(fz, "current_gate_state", return_value=(0.4, 6000.0, 0)), \
                 mock.patch.object(fz, "http_get", side_effect=fake_get), \
                 mock.patch.object(fz.time, "sleep"):
                rc = fz.sync(db, limit=100, delay=0,
                             rails=[("hollywood", "a.php"), ("bollywood", "b.php")], quiet=True)
            self.assertEqual(rc, 0)
            self.assertEqual(seen, ["https://fzmovies.host/a.php"],
                             "a 429 must stop the whole run, not just the rail")


class RailTableTests(unittest.TestCase):

    def test_rails_cover_all_three_catids_and_every_measured_by_value(self):
        joined = " ".join(path for _name, path in fz.LISTING_RAILS)
        for catid in ("1", "2", "3"):
            self.assertIn(f"catID={catid}", joined)
        for by in ("latest", "date", "rating", "downloads"):
            self.assertIn(f"by={by}", joined)

    def test_rail_names_are_unique_so_a_subset_flag_cannot_be_ambiguous(self):
        names = [name for name, _path in fz.LISTING_RAILS]
        self.assertEqual(len(names), len(set(names)))

    def test_a_named_rail_subset_selects_only_what_was_asked_for(self):
        subset = fz._rail_subset(["hollywood", "no-such-rail"])
        self.assertEqual(subset, [("hollywood", "movieslist.php?catID=2&by=latest")])
        self.assertEqual(len(fz._rail_subset([])), len(fz.LISTING_RAILS))

    def test_every_rail_is_a_site_relative_path(self):
        for name, path in fz.LISTING_RAILS:
            self.assertFalse(path.startswith(("http://", "https://")), name)
            self.assertTrue(fz.absolute(path).startswith(fz.BASE_URL + "/"), name)

    def test_the_rail_table_does_not_invent_a_shape_the_homepage_never_showed(self):
        """The dubbed rail has no `alpha.php` and no `hotmovies.php`; asserting
        that keeps a future edit from guessing rails into existence."""
        joined = " ".join(path for _name, path in fz.LISTING_RAILS)
        self.assertNotIn("alpha.php?catID=3", joined)
        self.assertNotIn("hotmovies.php?catID=1", joined)
        self.assertNotIn("genre.php?catID=1", joined)
        self.assertIn("movieslist.php?catID=3&by=alpha", joined)


class UrlHygieneTests(unittest.TestCase):

    def test_absolute_builds_site_urls_and_nothing_else(self):
        self.assertEqual(fz.absolute("movieslist.php?catID=2"),
                         "https://fzmovies.host/movieslist.php?catID=2")
        self.assertEqual(fz.absolute("/imdb_images/X.jpg"), "https://fzmovies.host/imdb_images/X.jpg")

    def test_ad_and_tracking_hosts_are_recognised_as_junk(self):
        for url in ("https://www.googletagmanager.com/gtag/js",
                    "https://doubleclick.net/x",
                    "https://hippierrapiner.com/pop"):
            self.assertTrue(fz._is_junk(url), url)
        self.assertFalse(fz._is_junk("https://fzmovies.host/movie-A--hmp4.htm"))
        self.assertFalse(fz._is_junk("https://notdoubleclick.net.x/"))

    def test_the_module_never_targets_another_people_service(self):
        hosts = {fz.BASE_URL}
        self.assertEqual(hosts, {"https://fzmovies.host"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
