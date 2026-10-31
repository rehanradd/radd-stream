#!/usr/bin/env python3
"""Provenance-suppression tests for the public edge (`redact.py` + `viewer.py`).

Three kinds of guarantee, because one alone is not enough:

* **Structural** — for every public response, no key name from
  ``redact.PROVENANCE`` survives anywhere in the tree. This is an invariant, not
  a search: a new ledger column that nobody reviewed is invisible by construction.
* **Sentinel** — a value can escape under a renamed key, so every public body
  (JSON, M3U, dashboard HTML) is also text-scanned for the site slugs and hoster
  names we planted in the fixture.
* **Zero data loss** — the same fixture must leave the ledger untouched and still
  resolve a playable URL, and the operator port must still see everything. Hiding
  provenance from a client may never mean losing it from the record.

Plus the two mechanisms the plan depends on: opaque handles (round-trip and
tamper) and the rate-limit buckets.

Offline and stdlib-only: both servers run on loopback with ephemeral ports and
``RADD_SKIP_LIVE_ENRICH=1`` keeps the ingest path off the network.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("RADD_SKIP_LIVE_ENRICH", "1")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import catalog_api          # noqa: E402
import catalog_v2           # noqa: E402
import fast_fetch           # noqa: E402
import redact               # noqa: E402
import viewer               # noqa: E402

#: What we plant, and therefore what must never be found in a public body.
SENTINELS = (
    "vegamovies", "pixeldrain", "hubcloud", "hdhub4u", "vegadrive",
    "gamerxyt", "direct-cloud", "greenmotors",
)

#: The operator port is fail-closed: every route on it now answers 401 without a
#: bearer token, because loopback is a boundary and not a credential. An HTTP test
#: that means to *be* the operator has to say so, which is the honest version of
#: the old fixture's silent assumption that reaching the socket was enough.
OPERATOR_TOKEN = "redact-suite-operator-credential"
TOKEN_ENV = "RADD_ADMIN_TOKEN"

#: Where the public handler writes the operator's playback counters. It counts at
#: `accounts_api.state_db()`, which is the production ledger unless a test says
#: otherwise — measured: an unpatched run of this suite put 42 `playback_start`
#: rows into `/home/ubuntu/radd-stream-data/user_state.db`. A test that writes into
#: the numbers it is supposed to be protecting is not a test.
STATE_DB_ENV = "RADD_USER_STATE_DB"


def media(site, url, *, title=None, clean_title="Example Film", year=2024,
          quality="1080p", source_name="⚡ PixelDrain [Direct CDN]", service="pixeldrain",
          final_url="https://pixeldrain.com/u/AbCdEf12", poster=None, adult=0,
          release_title=None):
    """One ingest payload in exactly the shape a scraper hands the ledger."""
    title = title or f"{clean_title} ({year}) {quality} [2.4GB] – {site}"
    return {
        "url": url,
        "slug": url.rstrip("/").split("/")[-1],
        "title": title,
        "clean_title": clean_title,
        "year": year,
        "content_type": "movie",
        "seasons": None,
        "poster_url": poster,
        "backdrop_urls": None,
        "imdb_rating": 7.1,
        "genres": json.dumps(["Action"]),
        "synopsis": f"A film seen on {site}.",
        "is_18_plus": adult,
        "is_animated": 0,
        "source_site": site,
        "industry": "Hollywood",
        "country": "USA",
        "language": "English",
        "canonical_key": fast_fetch.generate_canonical_key(clean_title, year),
        "tmdb_id": None,
        "imdb_id": None,
        "releases": [{
            "release_title": release_title or f"{clean_title} ({year}) {quality} {service}",
            "quality": quality,
            "codec": "x264",
            "size": "2.4GB",
            "languages": "English",
            "season": None,
            "episode": None,
            "intermediate_url": f"https://{site}.example/release",
            "sources": [{
                "source_name": source_name,
                "service": service,
                "resource_id": f"{site}-res-1",
                "source_url": f"https://{site}.example/dl/1",
                "final_url": final_url,
                "is_temporary": 0,
            }],
        }],
    }


class FixtureMixin(unittest.TestCase):
    """A temp ledger with three attributed posts (one adult), projected into v2 too."""

    def make_ledger(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "redact.db"
        self.patches = [
            patch.object(fast_fetch, "DB_PATH", self.db_path),
            patch.object(fast_fetch, "fetch_cinemeta_metadata", return_value=None),
            patch.object(viewer, "DB_PATH", self.db_path),
        ]
        for p in self.patches:
            p.start()
        fast_fetch.init_db()
        self.post_id = fast_fetch.save_scraped_data(
            media("vegamovies", "https://vegamovies.example/example-film/"))
        self.second_id = fast_fetch.save_scraped_data(
            media("hdhub4u", "https://hdhub4u.example/example-film-hd/",
                  quality="720p", service="hubcloud", source_name="HubCloud Link",
                  # `pixel.` is HubCloud's byte server; a bare `/drive/` host is a
                  # landing page and is refused by the resolver on purpose.
                  final_url="https://pixel.hubcloud.foo/drive/xyz",
                  poster="https://img.hdhub4u.example/poster.jpg"))
        self.adult_id = fast_fetch.save_scraped_data(
            media("gamerxyt", "https://gamerxyt.example/adult-title/",
                  clean_title="Adult Diary", source_name="Gamerxyt Mirror",
                  service="gamerxyt", final_url="https://gamerxyt.click/f/9",
                  adult=1))
        viewer._ensure_schema()
        os.environ["RADD_STREAM_SECRET"] = "test-secret-for-redact-suite"
        self.addCleanup(os.environ.pop, "RADD_STREAM_SECRET", None)
        self.addCleanup(setattr, viewer, "_SIGNING_SECRET", None)
        viewer._SIGNING_SECRET = None
        self.addCleanup(lambda: redact.limiter._buckets.clear())

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.temp_dir.cleanup()

    # -- ledger readers (never the public surface) --------------------------- #
    def one(self, sql, params=()):
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            return conn.execute(sql, params).fetchone()

    def source_id(self, post_id):
        return self.one("SELECT s.id FROM download_sources s "
                        "JOIN releases r ON r.id = s.release_id WHERE r.post_id = ?",
                        (post_id,))["id"]


# ── 1. redact.py, in isolation ───────────────────────────────────────────────

class ProjectionTests(FixtureMixin):
    def setUp(self):
        self.make_ledger()

    def test_project_denies_any_key_not_named_in_the_view(self):
        row = dict(self.one(
            "SELECT s.* FROM download_sources s JOIN releases r ON r.id = s.release_id "
            "WHERE r.post_id = ?", (self.post_id,)))
        view = redact.project(row, "link")
        self.assertTrue(row, "the fixture row itself must still carry everything")
        for key in redact.PROVENANCE:
            self.assertNotIn(key, view)
        # New columns are invisible until someone publishes them on purpose.
        self.assertNotIn("brand_new_column", redact.project(
            {**row, "brand_new_column": "hubcloud"}, "link"))

    def test_project_refuses_to_publish_a_view_that_names_provenance(self):
        """An allowlist typo must fail loudly, not leak quietly."""
        original = redact.VIEWS["link"]
        redact.VIEWS["link"] = frozenset(original | {"source_site"})
        try:
            with self.assertRaises(redact.ProjectionError):
                redact.project({"id": 1, "source_site": "vegamovies"}, "link")
        finally:
            redact.VIEWS["link"] = original

    def test_scrub_removes_nested_provenance_and_never_mutates_input(self):
        tree = {"work": {"title": "Dune – VegaMovies", "sites": [{"page_url": "https://x"}]},
                "prints": [{"label": "1080p WEB-DL hubcloud", "url": "https://hdhub4u/a"}]}
        kept = json.dumps(tree, sort_keys=True)
        clean = redact.scrub(tree)
        self.assertEqual(json.dumps(tree, sort_keys=True), kept, "scrub must copy")
        self.assertNotIn("sites", clean["work"])
        self.assertNotIn("page_url", json.dumps(clean))
        self.assertNotIn("url", clean["prints"][0])
        self.assertNotIn("vegamovies", clean["work"]["title"].lower())
        self.assertNotIn("hubcloud", clean["prints"][0]["label"].lower())

    def test_scrub_text_uses_the_curated_vocabulary_only(self):
        redact.set_needles({"vegamovies", "pixeldrain"}, {"vegamovies"})
        self.addCleanup(redact.set_needles, redact.BASE_NEEDLES, redact.BASE_NEEDLES)
        # A detection needle never rewrites text: only the text vocabulary does.
        self.assertEqual(redact.scrub_text("My Pixeldrain Story"), "My Pixeldrain Story")
        self.assertEqual(redact.scrub_text("Dune – VegaMovies"), "Dune")

    def test_scrub_text_keeps_honest_labels_intact(self):
        redact.set_needles(redact.site_needles(), redact.site_text_needles())
        for text in ("Example Film (2024) 1080p WEB-DL - Part 2",
                     "{Hindi – Amazon Prime} Example Film 720p",
                     "Example Film [470MB] x265 HEVC 10-bit",
                     "Example Film S01E03 480p CAM"):
            self.assertEqual(redact.scrub_text(text), text,
                             "cleaning must not eat the useful half of a title")

    def test_trailing_domain_suffix_is_dropped_even_for_an_unknown_site(self):
        redact.set_needles(redact.site_needles(), redact.site_text_needles())
        for suffix in ("somebrand.click", "a-new-mirror.fit", "unknown.site"):
            out = redact.scrub_text(f"Example Film (2024) 1080p – {suffix}")
            self.assertTrue(out.startswith("Example Film"), out)
            self.assertNotIn("somebrand", out)
            self.assertNotIn("new-mirror", out)
            self.assertNotIn("unknown", out)

    def test_public_label_is_built_from_structured_columns_only(self):
        label = redact.public_label({"quality": "1080p", "codec": "x264", "size": "2.4GB",
                                     "languages": "Hindi English", "season": 1,
                                     "episode": 3, "release_title": "Dune – VegaMovies"})
        self.assertIn("1080p", label)
        self.assertIn("2.4GB", label)
        for needle in SENTINELS:
            self.assertNotIn(needle, label.lower())

    def test_adult_clause_is_the_one_predicate(self):
        self.assertEqual(redact.adult_clause("posts"),
                         "(posts.is_18_plus IS NULL OR posts.is_18_plus = 0)")


class DisplayTextTests(unittest.TestCase):
    """The rules that clean a *sentence*, not a word.

    A brand we do not know is the hard case: the vocabulary cannot name it, and
    guessing from word shape would eat the catalog. What saves us is that our
    scrapers announce a server with a marker word — so the sentence goes, not the
    language. These are the shapes found in the real 109k ledger.
    """

    def setUp(self):
        redact.set_needles(redact.site_needles(), redact.site_text_needles())
        self.addCleanup(redact.set_needles, redact.BASE_NEEDLES, redact.BASE_NEEDLES)

    def test_a_server_introduction_is_cut_whole(self):
        # "IQSmart"/"VidZee"/"Peachify" are not in any vocabulary — plain-shaped
        # words we have never heard. The marker is enough.
        for text, want in (
                ("Dune Stream Server IQSmart", "Dune"),
                ("Dune Stream Server VidZee - Recommended", "Dune"),
                ("Dune (2024) S01E02 Server 03", "Dune (2024) S01E02"),
                ("Dune (2024) S01E02 Server", "Dune (2024) S01E02"),
                ("Dune (2024) Stream Movie HQ", "Dune (2024)")):
            self.assertEqual(redact.scrub_text(text), want, text)

    def test_a_label_that_is_only_a_server_introduction_says_nothing(self):
        # Empty beats vague: the caller falls back to our own `clean_title`.
        for text in ("Direct Link", "Watch Online", "Google Drive Direct Link",
                     "Online Stream", "Server 2", "All Direct Links"):
            self.assertEqual(redact.scrub_text(text), "", text)

    def test_the_marker_word_alone_is_not_a_server(self):
        # The cut is anchored to a marker *phrase*, or to a marker at the end of
        # the string, precisely so that a real title keeps its own words.
        for text in ("The Server Room (2019)", "Server (2022) Full Movie",
                     "The Links (1979)"):
            self.assertEqual(redact.scrub_text(text), text)

    def test_a_digit_leading_brand_is_a_brand_not_a_size(self):
        # 1XPlayer / 7starhd / 9xmovies all open with a digit; 1080p / 650MB /
        # 1920x1080 genuinely are sizes and must survive the cleaner.
        for brand in ("1XPlayer", "7starhd", "9xmovies", "g-direct", "v-cloud"):
            self.assertTrue(redact.brand_shaped(brand.lower()), brand)
        for size in ("1080p", "2160p", "650MB", "1920x1080", "4K", "10-bit"):
            self.assertFalse(redact.brand_shaped(size.lower()), size)
        redact.set_needles({"1xplayer", "vegamovies"})
        out = redact.scrub_text("Dune (2024) Online Stream (1XPlayer) HD")
        self.assertNotIn("1xplayer", out.lower())
        self.assertTrue(out.startswith("Dune (2024)"), out)

    def test_a_deleted_domain_leaves_no_orphan_tld(self):
        out = redact.scrub_text("The Terminal List (2026) 1080p WEB-DL x264 "
                                "| Vegamovies.is")
        self.assertNotIn(".is", out)
        self.assertTrue(out.endswith("x264"), out)

    def test_a_category_list_never_carries_a_domain_or_markup(self):
        scraped = json.dumps(["drama", "rogmovies.one", '{"@type":"ListItem"',
                              '"name":"Drama"}}', "secure.gravatar.com",
                              "download-dune-2024", "Action & Adventure"])
        self.assertEqual(json.loads(redact.public_list(scraped)),
                         ["drama", "Action & Adventure"])

    def test_a_cleaning_pass_that_empties_the_text_does_not_restore_it(self):
        # An older fallback returned the original when cleaning left nothing,
        # which put back the exact brand that had just been deleted.
        redact.set_needles({"rogmovies", "officialrogmovies"})
        self.assertEqual(redact.scrub_text("Rogmovies OfficialRogmovies"), "")

    def test_character_references_are_resolved_before_anything_is_matched(self):
        # A page says an apostrophe as `&#8217;` and a dash as `&#8211;`. Passing
        # that through is how the app came to display `JoJo&#8217;s`; decoding is
        # also what lets the brand rules see `Vegamovies` inside `Vega&sh;movies`
        # shaped text, so it happens first, not last.
        for text, want in (
                ("JoJo&#8217;s Bizarre Adventure", "JoJo’s Bizarre Adventure"),
                ("Chapter III &#8211; The Curse", "Chapter III – The Curse"),
                ("Tom &amp; Jerry Kids Show", "Tom & Jerry Kids Show"),
                ("Klaus&nbsp;Production", "Klaus Production"),
                ("&#039;71", "'71")):
            self.assertEqual(redact.scrub_text(text), want, text)

    def test_a_double_escape_is_resolved_once_more_and_no_further(self):
        # A CMS that escaped its own escapes needs the second pass; the bound is
        # the point — a long `&amp;amp;…` chain must not make this spin forever.
        self.assertEqual(redact.scrub_text("Tom &amp;amp; Jerry"), "Tom & Jerry")
        deep = "Tom " + "&amp;" * 40 + " Jerry"
        self.assertTrue(redact.scrub_text(deep).startswith("Tom &"), deep[:60])


class HandleTests(unittest.TestCase):
    SECRET = "unit-test-secret"

    def test_token_round_trip_and_tamper_rejection(self):
        for number in (1, 7, 4096, 2 ** 31 - 1):
            token = redact.mint_token(number, self.SECRET)
            self.assertNotIn(str(number), token, "the handle must not be the id")
            self.assertEqual(redact.parse_token(token, self.SECRET), number)
        forged = redact.mint_token(42, self.SECRET)
        self.assertIsNone(redact.parse_token(forged[:-2] + "xx", self.SECRET))
        self.assertIsNone(redact.parse_token(forged, "another-secret"))
        self.assertIsNone(redact.parse_token("not-a-token", self.SECRET))
        self.assertIsNone(redact.parse_token("", self.SECRET))

    def test_plain_digits_parse_only_where_we_allow_enumeration(self):
        """Row ids are enumerable, so the plain form survives on loopback for the
        operator's curl and dies on the public port, where only a handle we minted
        resolves."""
        self.assertEqual(redact.parse_token("123", self.SECRET), 123)
        self.assertIsNone(redact.parse_token("123", self.SECRET, signed_only=True))
        self.assertIsNone(redact.parse_token(123, self.SECRET, signed_only=True))
        token = redact.mint_token(123, self.SECRET)
        self.assertEqual(redact.parse_token(token, self.SECRET, signed_only=True), 123)

    def test_text_handles_round_trip(self):
        value = "https://img.hdhub4u.example/poster.jpg"
        token = redact.mint_text(value, self.SECRET)
        self.assertNotIn("hdhub4u", token)
        self.assertEqual(redact.parse_text(token, self.SECRET), value)
        self.assertIsNone(redact.parse_text(token[:-1] + "A", self.SECRET))

    def test_stream_secret_is_stable_and_persisted_outside_the_checkout(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "catalog.db"
            sqlite3.connect(path).execute("CREATE TABLE posts (id INTEGER PRIMARY KEY)")
            sqlite3.connect(path).commit()
            os.environ.pop("RADD_STREAM_SECRET", None)
            first = redact.stream_secret(path)
            self.assertEqual(redact.stream_secret(path), first)
            stored = sqlite3.connect(path).execute(
                "SELECT value FROM server_state WHERE key = 'stream_secret'").fetchone()
            self.assertEqual(stored[0], first)

    def test_art_value_passes_public_cdn_and_wraps_everything_else(self):
        url = redact.public_art_value("https://image.tmdb.org/t/p/w500/a.jpg", 5,
                                      self.SECRET, "http://our.host", "poster", 0)
        self.assertEqual(url, "https://image.tmdb.org/t/p/w500/a.jpg")
        wrapped = redact.public_art_value("https://img.hdhub4u.example/a.jpg", 5,
                                          self.SECRET, "http://our.host", "poster", 0)
        self.assertTrue(wrapped.startswith("http://our.host/api/v1/art?id="), wrapped)
        self.assertNotIn("hdhub4u", wrapped)
        self.assertIn("t=works", redact.public_art_value(
            "https://img.hdhub4u.example/a.jpg", 5, self.SECRET, "http://our.host",
            "backdrop", 2, table="works"))
        self.assertTrue(redact.public_art_value(
            "https://img.hdhub4u.example/a.jpg", 5, self.SECRET, "", "poster", 0
        ).startswith("/api/v1/art?"))


class RateLimiterTests(unittest.TestCase):
    def test_bucket_consumes_resets_and_reports_the_ietf_triple(self):
        limiter = redact.RateLimiter(limits={"browse": (3, 60.0)})
        client = "10.0.0.1"
        for expected in (2, 1, 0):
            verdict = limiter.check("browse", client)
            self.assertTrue(verdict["allowed"])
            self.assertEqual(verdict["remaining"], expected)
            self.assertEqual(verdict["limit"], 3)
            self.assertGreaterEqual(verdict["reset"], 0)
        blocked = limiter.check("browse", client)
        self.assertFalse(blocked["allowed"])
        self.assertGreaterEqual(blocked["retry_after"], 1)
        names = [name for name, _ in limiter.headers(blocked)]
        self.assertEqual(names, ["RateLimit-Limit", "RateLimit-Remaining", "RateLimit-Reset"])
        # A different client is a different bucket.
        self.assertTrue(limiter.check("browse", "10.0.0.2")["allowed"])
        # The window reopens.
        later = __import__("time").time() + 120
        self.assertTrue(limiter.check("browse", client, moment=later)["allowed"])

    def test_documented_budgets(self):
        self.assertEqual(redact.BUCKET_LIMITS["play"][0], 30)
        self.assertEqual(redact.BUCKET_LIMITS["browse"][0], 60)
        self.assertEqual(redact.BUCKET_LIMITS["reports"][0], 10)

    def test_the_bucket_key_is_the_address_the_edge_saw_not_the_one_claimed(self):
        # Measured live on the public edge before this existed: three requests
        # with three invented X-Forwarded-For values each got `Remaining: 59`,
        # because the limiter keyed on the caller's own string.
        class _Handler:
            def __init__(self, peer, **headers):
                self.client_address = (peer, 41234)
                self.headers = dict(headers)

        behind_proxy = "203.0.113.7"
        spoofed = _Handler("127.0.0.1",
                           **{"X-Real-IP": behind_proxy,
                              "X-Forwarded-For": "1.2.3.4, 9.9.9.9"})
        self.assertEqual(redact.client_ip(spoofed), behind_proxy,
                         "X-Real-IP is what nginx set from $remote_addr; the "
                         "first XFF entry is what the caller typed")
        # With no X-Real-IP (a proxy that only appends), the entry our edge
        # appended is the last one, not the first.
        appended = _Handler("127.0.0.1",
                            **{"X-Forwarded-For": "1.2.3.4, 9.9.9.9"})
        self.assertEqual(redact.client_ip(appended), "9.9.9.9")
        # A direct hit that did not come through nginx trusts no header at all.
        direct = _Handler("198.51.100.9",
                          **{"X-Forwarded-For": "1.2.3.4", "X-Real-IP": "1.2.3.4"})
        self.assertEqual(redact.client_ip(direct), "198.51.100.9")
        # And a caller cannot make two spoofed strings look like two strangers:
        # through our edge they arrive as one bucket, keyed on the real peer.
        limiter = redact.RateLimiter(limits={"browse": (2, 60.0)})
        for claim in ("1.2.3.4", "9.9.9.9", "192.0.2.66"):
            key = redact.client_ip(_Handler("127.0.0.1",
                                            **{"X-Real-IP": "203.0.113.7",
                                               "X-Forwarded-For": claim}))
            self.assertEqual(key, "203.0.113.7")
        for _ in range(2):
            self.assertTrue(limiter.check("browse", "203.0.113.7")["allowed"])
        self.assertFalse(limiter.check("browse", "203.0.113.7")["allowed"])


class NeedleVocabularyTests(FixtureMixin):
    def setUp(self):
        self.make_ledger()

    def test_needles_grow_with_the_data_not_with_the_source(self):
        broad = redact.site_needles(self.db_path)
        self.assertIn("vegamovies", broad)          # curated baseline
        self.assertIn("gamerxyt", broad)            # whatever the ledger recorded
        self.assertIn("pixeldrain", broad)          # a hoster service column
        text = redact.site_text_needles(self.db_path)
        self.assertIn("vegamovies", text)
        self.assertNotIn("unknown", text)
        for token in redact.GENERIC_TOKENS:
            self.assertNotIn(token, broad, "an English word is not a needle")

    def test_source_name_prose_contributes_only_its_brand_word(self):
        broad = redact.site_needles(self.db_path)
        self.assertIn("hubcloud", broad)
        for whole in ("hubcloud link", "⚡ pixeldrain [direct cdn]"):
            self.assertNotIn(whole, broad)


# ── 2. the live HTTP edge ────────────────────────────────────────────────────

class UnknownBrandAndDanglingWordTests(unittest.TestCase):
    """The two generic rules, measured against the whole 96k catalog.

    A curated needle list only knows the brands it has already met, and a
    deletion always leaves a hole behind. Both are closed by shape, and shape is
    the dangerous part: these tests are the honest text that the shape must not
    touch, taken from titles that really are in the catalog.
    """

    def setUp(self):
        redact.set_needles(redact.BASE_NEEDLES, redact.BASE_NEEDLES)
        self.addCleanup(redact.set_needles, redact.BASE_NEEDLES, redact.BASE_NEEDLES)

    def test_an_unheard_of_domain_goes_without_the_vocabulary_knowing_it(self):
        # None of these is a needle: the registry has never seen the mirror.
        for text, want in (
                ("Dune (2024) 1080p KatDrama.com", "Dune (2024) 1080p"),
                ("MovieHeist.net Presents", "Presents"),
                ("Watch on Moviesbaba.in Today", "Watch on Today"),
                ("Attack on Titan in PikaHD.com", "Attack on Titan in"),
                ("Dune – Some.Site", "Dune"),
                ("i.ytimg.com art", "art")):
            self.assertEqual(redact.scrub_text(text), want, text)

    def test_a_dotted_title_is_not_a_domain(self):
        # The catalog's own honest titles. Every one has a final segment that no
        # registrar sells, or a label too short to be a hostname.
        for text in ("Ra.One", "B.Tech Girly Gang", "C.I.Ape (2021) Dual Audio",
                     "A.I.SHA My Virtual Girlfriend", "Tenali Ramakrishna BA.BL",
                     "Unbending Mr.Fang", "U.S.A. Today", "Train.Dreams",
                     "Wedding.con", "The.Shadow.Effect.2017..XviD.AC3 EVO",
                     "Dune (2024) 5.1 DOLBY 10.12 GB 1.5GB x264",
                     "A film about e.g. money, i.e. value", "Mr. Jones",
                     "Kidnapping Inc.", "C.I.D."):
            self.assertTrue(redact.scrub_text(text), f"{text} was emptied")
        for text in ("Ra.One (2011)", "Train.Dreams", "Kidnapping Inc.",
                     "C.I.D.", "U.S.A. Today"):
            self.assertEqual(redact.scrub_text(text), text)

    def test_a_deletion_does_not_leave_a_dangling_connective(self):
        for text, want in (
                ("Dune (2024) Watch Free on KatDrama.com", "Dune (2024) Watch Free"),
                ("Movie (2024) Download Links of Vegamovies.is",
                 "Movie (2024) Download Links"),
                ("Dune and VegaMovies", "Dune"),
                ("Kong King of the Apes In All Vegamovies.com .",
                 "Kong King of the Apes In All")):
            out = redact.scrub_text(text)
            self.assertEqual(out, want, text)
            self.assertFalse(out.endswith((" on", " of", " and", " for", " .")), out)

    def test_a_hindi_blurb_loses_its_dangling_postposition(self):
        text = ("The Tinder Swindler 2022 डाउनलोड के लिए उपलब्ध सिर्फ़ "
                "KatMoviehd.pm पर | Dual Audio")
        out = redact.scrub_text(text)
        self.assertNotIn("पर", out)
        self.assertTrue(out.endswith("उपलब्ध | Dual Audio"), out)

    def test_a_one_word_title_is_never_peeled(self):
        # "From" and "Is" are real catalog titles, not leftovers.
        for text in ("From", "IS", "FROM", "Is", "The", "A"):
            self.assertEqual(redact.scrub_text(text), text)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class PublicEdgeHttpTests(FixtureMixin):
    @classmethod
    def setUpClass(cls):
        cls.saved_token = os.environ.get(TOKEN_ENV)
        os.environ[TOKEN_ENV] = OPERATOR_TOKEN
        cls.saved_state = os.environ.get(STATE_DB_ENV)
        cls.state_tmp = tempfile.TemporaryDirectory()
        os.environ[STATE_DB_ENV] = str(Path(cls.state_tmp.name) / "user_state.db")
        cls.public_server = viewer.make_server("127.0.0.1", 0, operator=False)
        cls.operator_server = viewer.make_server("127.0.0.1", 0, operator=True)
        for server in (cls.public_server, cls.operator_server):
            threading.Thread(target=server.serve_forever, daemon=True).start()
        cls.public_port = cls.public_server.server_address[1]
        cls.operator_port = cls.operator_server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        for server in (cls.public_server, cls.operator_server):
            server.shutdown()
            server.server_close()
        if cls.saved_token is None:
            os.environ.pop(TOKEN_ENV, None)
        else:
            os.environ[TOKEN_ENV] = cls.saved_token
        if cls.saved_state is None:
            os.environ.pop(STATE_DB_ENV, None)
        else:
            os.environ[STATE_DB_ENV] = cls.saved_state
        cls.state_tmp.cleanup()

    def setUp(self):
        self.make_ledger()
        redact.limiter._buckets.clear()

    def tearDown(self):
        super().tearDown()
        redact.limiter._buckets.clear()

    def get(self, path, port, follow=False):
        url = f"http://127.0.0.1:{port}{path}"
        request = urllib.request.Request(url)
        if port == self.operator_port:
            request.add_header("Authorization", "Bearer " + OPERATOR_TOKEN)
        opener = urllib.request.build_opener() if follow else \
            urllib.request.build_opener(_NoRedirect)
        try:
            with opener.open(request, timeout=10) as response:
                return response.status, dict(response.headers), response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            return error.code, dict(error.headers), error.read().decode("utf-8")

    def public_json(self, path):
        status, headers, body = self.get(path, self.public_port)
        self.assertEqual(status, 200, body)
        return json.loads(body), headers

    def assert_no_provenance(self, payload, label):
        found = redact.provenance_keys(payload)
        self.assertEqual(found, [], f"{label} publishes provenance keys {found}")
        leaks = redact.is_clean(payload)
        self.assertEqual(leaks, [], f"{label} leaks provenance values: {leaks}")

    def public_detail(self, post_id):
        """`/api/v1/posts/{id}` answers inside a {"success", "data"} envelope."""
        envelope, _ = self.public_json(f"/api/v1/posts/{post_id}")
        return envelope["data"]

    def operator_detail(self, post_id):
        status, _, body = self.get(f"/api/v1/posts/{post_id}", self.operator_port)
        self.assertEqual(status, 200, body)
        return json.loads(body)["data"]

    def test_the_playback_counters_cannot_reach_the_production_ledger(self):
        """Every play this suite makes is counted by the real handler, into
        `accounts_api.state_db()`. If that ever resolves to the host's data disk
        again, the operator's playback totals become test traffic — so the pin is
        asserted, not assumed."""
        import accounts_api
        served = accounts_api.state_db()
        self.assertTrue(str(served).startswith(self.state_tmp.name),
                        "analytics wrote outside the test sandbox: " + str(served))
        self.get("/api/v1/stats", self.public_port)
        handle = redact.mint_token(self.source_id(self.post_id),
                                   viewer.signing_secret())
        self.get(f"/api/v1/stream?id={handle}&redirect=0", self.public_port)
        self.assertTrue(Path(self.state_tmp.name).exists())
        days = [row[0] for row in sqlite3.connect(str(served)).execute(
            "SELECT metric FROM usage_metric")]
        self.assertEqual(days, ["playback_start"],
                         "the sandbox ledger, and only it, carries the counts")

    def test_the_bulk_dump_is_operator_only(self):
        """`/api/data` returns every post in one response. Projected or not, that
        is a clone of the whole collection in a single request — and at 109k posts
        it is also a self-inflicted denial of service on this box. Clients use the
        paginated list, so the public port does not answer it at all."""
        status, _, body = self.get("/api/data", self.public_port)
        self.assertEqual(status, 404, body)

    def test_dashboard_stats_project_to_scale_without_naming_sites(self):
        """Checked where the panel is built: the public projection is an
        allowlist, and a key name can hide a site just as well as a value."""
        data = viewer.fetch_database_payload(full=False)
        self.assert_no_provenance(data, "dashboard payload")
        for key in list(data["stats"]):
            self.assertIn(key, redact.VIEWS["dashboard_stats"],
                          "the dashboard panel is an allowlist, not a deny-list")
        for hidden in ("vega_posts", "rog_posts", "ssr_posts", "kat_posts",
                       "star7_posts", "sitemap_vega", "by_site", "sites"):
            self.assertNotIn(hidden, data["stats"], f"{hidden} names a site")
            self.assertNotIn(hidden, data)
        self.assertTrue(data["posts"], "hiding provenance must not hide the catalog")
        self.assertTrue(data["posts"][0]["clean_title"].startswith("Example Film"))
        for needle in SENTINELS:
            self.assertNotIn(needle, json.dumps(data).lower())

    def test_post_list_and_detail_are_clean(self):
        posts, _ = self.public_json(f"/api/v1/posts?limit=20")
        self.assert_no_provenance(posts, "/api/v1/posts")
        detail = self.public_detail(self.post_id)
        self.assert_no_provenance(detail, "/api/v1/posts/{id}")
        self.assertNotIn("source_pages", detail)
        link = detail["releases"][0]["sources"][0]
        self.assertTrue(link["stream_id"], "the handle is what replaces the URL")
        self.assertNotIn("url", link)
        self.assertIn("/api/v1/stream?id=", link["play_url"])

    def test_m3u_is_our_playlist_not_the_upstreams(self):
        status, _, body = self.get(f"/api/m3u?id={self.post_id}", self.public_port)
        self.assertEqual(status, 200)
        self.assertIn("#EXTM3U", body)
        for line in body.splitlines():
            if line.startswith("#EXTINF"):
                self.assertNotIn("] ", line, "the bracketed hoster tag must be gone")
            if line and not line.startswith("#"):
                self.assertTrue(line.startswith("http://127.0.0.1:"), line)
                self.assertIn("/api/v1/stream?id=", line)
        for needle in SENTINELS:
            self.assertNotIn(needle, body.lower(), body)

    def test_stream_handle_redirects_and_reports_nothing_extra(self):
        detail = self.public_detail(self.post_id)
        handle = detail["releases"][0]["sources"][0]["stream_id"]
        status, headers, body = self.get(f"/api/v1/stream?id={handle}&redirect=0",
                                         self.public_port)
        self.assertEqual(status, 200, body)
        payload = json.loads(body)
        self.assert_no_provenance(payload, "stream redirect=0")
        self.assertTrue(payload["success"])
        self.assertNotIn("url", payload)
        # The 302 model: bytes go direct, so a capture shows the upstream host.
        # That is the accepted trade (documented in redact.py); the redirect itself
        # must still work, and must be reached by our handle alone.
        status, headers, _ = self.get(f"/api/v1/stream?id={handle}", self.public_port)
        self.assertEqual(status, 302)
        self.assertTrue(headers["Location"].startswith("https://pixeldrain.com/"))

    def test_row_ids_are_not_addresses_the_public_can_walk(self):
        """`1..3,070,247` is every link we own. A caller who could use a bare row
        id would harvest the whole library without our API ever naming a hoster,
        so the public port answers the plain form with the same 400 it gives a
        corrupt token — and loopback keeps it, because that is the operator's
        debugging handle."""
        raw = self.source_id(self.post_id)
        for path in (f"/api/v1/stream?id={raw}", f"/api/v1/stream?id={raw}&redirect=0",
                     f"/api/v1/art?id={self.post_id}&k=poster"):
            status, _, _ = self.get(path, self.public_port)
            self.assertEqual(status, 400, f"{path} accepted a row id")
        handle = redact.mint_token(raw, viewer.signing_secret())
        status, _, _ = self.get(f"/api/v1/stream?id={handle}", self.public_port)
        self.assertIn(status, (200, 302), "the handle still works")
        status, _, _ = self.get(f"/api/v1/stream?id={raw}", self.operator_port)
        self.assertIn(status, (200, 302), "operator curl keeps the plain id")

    def test_art_handle_redirects_without_naming_the_image_host(self):
        posts, _ = self.public_json("/api/v1/posts?limit=20")
        target = [p for p in posts["results"] if p["id"] == self.second_id][0]
        ref = target["poster_url"]
        self.assertTrue(ref.startswith("http://127.0.0.1:") or ref.startswith("/api/v1/art"), ref)
        self.assertNotIn("hdhub4u", ref)
        status, headers, _ = self.get(ref.replace(f"http://127.0.0.1:{self.public_port}", ""),
                                      self.public_port)
        self.assertEqual(status, 302)
        self.assertIn("hdhub4u", headers["Location"],
                      "the redirect is where the upstream host legitimately appears")

    def test_adult_titles_are_indistinguishable_from_absent(self):
        posts, _ = self.public_json("/api/v1/posts?limit=50")
        self.assertNotIn(self.adult_id, [p["id"] for p in posts["results"]])
        status, _, body = self.get(f"/api/v1/posts/{self.adult_id}", self.public_port)
        self.assertEqual(status, 404, body)
        status, _, body = self.get(f"/api/m3u?id={self.adult_id}", self.public_port)
        self.assertEqual(status, 200)
        self.assertEqual(body.strip(), "", "empty, exactly like an unknown id")
        # A redirector addressed by a bare link id never sees the list, so it
        # needs the adult rule of its own.
        hidden_link = self.source_id(self.adult_id)
        status, _, _ = self.get(f"/api/v1/stream?id={hidden_link}", self.public_port)
        self.assertEqual(status, 400, "a raw row id is not a handle we handed out")
        handle = redact.mint_token(hidden_link, viewer.signing_secret())
        status, _, body = self.get(f"/api/v1/stream?id={handle}", self.public_port)
        self.assertEqual(status, 404, body)
        self.assertNotIn("Adult Diary", json.dumps(posts))
        art_handle = redact.mint_token(self.adult_id, viewer.signing_secret())
        status, _, _ = self.get(f"/api/v1/art?id={art_handle}&k=poster",
                                self.public_port)
        self.assertEqual(status, 404, "adult artwork must not redirect")
        self.assertEqual(self.one("SELECT is_18_plus FROM posts WHERE id = ?",
                                 (self.adult_id,))[0], 1,
                         "hidden is not deleted")

    def test_operator_only_routes_are_invisible_on_the_public_port(self):
        for path in ("/api/sitemap", "/api/fetch", "/api/heal", "/api/health-check",
                     "/api/v1/rules"):
            status, _, body = self.get(path, self.public_port)
            self.assertEqual(status, 404, f"{path} → {status} {body}")
            self.assertNotIn("pixeldrain", body)
            self.assertNotIn("gamerxyt", body)

    def test_the_bridge_table_is_served_only_on_the_operator_port(self):
        """`/api/v1/rules` hands a third party every hoster endpoint we unwrap —
        keeping it public is the exact hole the owner asked to close."""
        status, _, body = self.get("/api/v1/rules", self.operator_port)
        self.assertEqual(status, 200, body)
        self.assertIn("pixeldrain", json.loads(body)["services"])

    def test_dashboard_moves_to_the_operator_port(self):
        status, _, body = self.get("/", self.public_port)
        self.assertEqual(status, 200)
        for needle in SENTINELS:
            self.assertNotIn(needle, body.lower(), "the landing page is public")
        status, _, body = self.get("/", self.operator_port)
        self.assertEqual(status, 200)
        self.assertNotEqual(body, "", "the operator keeps the badge-bearing dashboard")

    def test_rate_limit_headers_and_429_on_the_public_port(self):
        _, headers, _ = self.get("/api/v1/stats", self.public_port)
        self.assertEqual(headers.get("RateLimit-Limit"), str(redact.BUCKET_LIMITS["reports"][0]))
        remaining = int(headers["RateLimit-Remaining"])
        _, headers2, _ = self.get("/api/v1/stats", self.public_port)
        self.assertEqual(int(headers2["RateLimit-Remaining"]), max(remaining - 1, 0))
        redact.limiter._buckets[("reports", "127.0.0.1")] = (0.0,
                                                            __import__("time").time())
        status, headers3, body = self.get("/api/v1/stats", self.public_port)
        self.assertEqual(status, 429, body)
        self.assertGreaterEqual(int(headers3["Retry-After"]), 1)
        self.assertEqual(json.loads(body)["error"], "rate_limited")

    def test_the_operator_port_still_sees_everything(self):
        """The audit trail survives: same data, full provenance, loopback only."""
        status, _, body = self.get("/api/data", self.operator_port)
        self.assertEqual(status, 200, body)
        data = json.loads(body)
        self.assertIn("vegamovies", body, "operator mode is the audit surface")
        self.assertIn("pixeldrain", body)
        self.assertIn("vega_posts", data["stats"],
                      "the per-site count map is exactly what the public loses")
        detail = self.operator_detail(self.post_id)
        self.assertTrue(detail["source_pages"], "every page we scraped it from")
        self.assertEqual(detail["releases"][0]["sources"][0]["final_url"],
                         "https://pixeldrain.com/u/AbCdEf12")

    def test_public_payloads_still_play_the_whole_catalog(self):
        """Every link a public client can use is reachable by handle alone."""
        detail = self.public_detail(self.post_id)
        handles = [s["stream_id"] for r in detail["releases"] for s in r["sources"]]
        self.assertTrue(handles)
        for handle in handles:
            status, headers, _ = self.get(f"/api/v1/stream?id={handle}", self.public_port)
            self.assertIn(status, (200, 302), f"{handle} → {status}")

    def test_a_non_numeric_pager_is_answered_not_crashed(self):
        """`?page=abc` used to raise out of the handler and the edge gave 502."""
        for path in ("/api/v1/posts?page=abc", "/api/v1/posts?page=",
                     "/api/v1/posts?page=999999999999999999999",
                     "/api/v1/posts?limit=abc", "/api/v1/posts?limit=-5",
                     "/api/v1/posts?limit=100000"):
            status, _, body = self.get(path, self.public_port)
            self.assertEqual(status, 200, f"{path} → {status}: {body[:120]}")
            payload = json.loads(body)
            self.assertGreaterEqual(payload["page"], 1, path)
            self.assertLessEqual(payload["limit"], 100, path)
            self.assertGreaterEqual(payload["limit"], 1, path)


# ── 3. zero data loss: hiding must not break healing or the ledger ───────────

class AdultDenialOnBothPortsTests(FixtureMixin):
    """The invariant, walked over real HTTP on both ports.

    Stated once, because the code and `AGENTS.md` disagreed about it: **no public
    surface ever lists or plays a flagged row; the authenticated, loopback-only
    operator panel may show that a flagged row exists and what its flag is; and
    stream and download deny a flagged row even there.**

    Measured in production, the leak was not a missing guard — `redact.adult_clause`
    filtered every row it was given. It was a *second* row for the same work that
    nobody had flagged, so every guard answered "allowed" truthfully. These tests
    therefore pin both halves: the deny must be uniform, and the row-level law must
    be reconciled at the work's key.
    """

    @classmethod
    def setUpClass(cls):
        cls.saved_token = os.environ.get(TOKEN_ENV)
        os.environ[TOKEN_ENV] = OPERATOR_TOKEN
        cls.saved_state = os.environ.get(STATE_DB_ENV)
        cls.state_tmp = tempfile.TemporaryDirectory()
        os.environ[STATE_DB_ENV] = str(Path(cls.state_tmp.name) / "user_state.db")
        cls.public_server = viewer.make_server("127.0.0.1", 0, operator=False)
        cls.operator_server = viewer.make_server("127.0.0.1", 0, operator=True)
        for server in (cls.public_server, cls.operator_server):
            threading.Thread(target=server.serve_forever, daemon=True).start()
        cls.public_port = cls.public_server.server_address[1]
        cls.operator_port = cls.operator_server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        for server in (cls.public_server, cls.operator_server):
            server.shutdown()
            server.server_close()
        if cls.saved_token is None:
            os.environ.pop(TOKEN_ENV, None)
        else:
            os.environ[TOKEN_ENV] = cls.saved_token
        if cls.saved_state is None:
            os.environ.pop(STATE_DB_ENV, None)
        else:
            os.environ[STATE_DB_ENV] = cls.saved_state
        cls.state_tmp.cleanup()

    def setUp(self):
        self.make_ledger()
        redact.limiter._buckets.clear()

    def tearDown(self):
        super().tearDown()
        redact.limiter._buckets.clear()

    def get(self, path, port):
        url = f"http://127.0.0.1:{port}{path}"
        request = urllib.request.Request(url)
        if port == self.operator_port:
            request.add_header("Authorization", "Bearer " + OPERATOR_TOKEN)
        opener = urllib.request.build_opener(_NoRedirect)
        try:
            with opener.open(request, timeout=10) as response:
                return response.status, response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            return error.code, error.read().decode("utf-8")

    def insert_twin(self, key, *, clean_title, year=2024, site="bolly4u",
                    url="https://bolly4u.example/adult-diary-hindi-download/"):
        """A ledger row that shares a work's key and was never flagged — the exact
        production shape: hindilinks4u's `4-play_2021` served while filmyhit's
        flagged copy of the same film was hidden."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO posts (url, slug, title, clean_title, year, content_type,"
                " source_site, is_18_plus, canonical_key)"
                " VALUES (?, ?, ?, ?, ?, 'movie', ?, 0, ?)",
                (url, url.rstrip("/").split("/")[-1], f"{clean_title} ({year})",
                 clean_title, year, site, key))
        return url

    def public_titles(self, query=""):
        path = "/api/v1/posts?limit=50"
        if query:
            path += "&q=" + urllib.parse.quote(query)
        status, body = self.get(path, self.public_port)
        self.assertEqual(status, 200, body)
        payload = json.loads(body)
        return payload["total"], [row["id"] for row in payload["results"]]

    # ── the deny must be uniform ────────────────────────────────────────────

    def test_stream_and_download_deny_a_flagged_link_on_the_operator_port_too(self):
        hidden_link = self.source_id(self.adult_id)
        handle = redact.mint_token(hidden_link, viewer.signing_secret())
        # A bare row id is not an address the public port accepts at all (400), so the
        # uniform-404 claim is made about handles on both ports and about the raw id on
        # the port that does take it.
        for path in (f"/api/v1/stream?id={handle}", f"/api/v1/download?id={handle}"):
            for label, port in (("public", self.public_port),
                                ("operator", self.operator_port)):
                status, body = self.get(path, port)
                self.assertEqual(status, 404, f"{label} {path} -> {status} {body}")
                self.assertEqual(json.loads(body), {"success": False, "error": "not_found"},
                                 f"{label} {path} explained the denial")
                self.assertNotIn("18+", body)
                self.assertNotIn("Adult Diary", body)
                self.assertNotIn("gamerxyt", body, f"{label} {path} named the hoster")

        status, body = self.get(f"/api/v1/stream?id={hidden_link}", self.operator_port)
        self.assertEqual(status, 404, body)
        self.assertEqual(json.loads(body), {"success": False, "error": "not_found"})

    def test_a_safe_link_still_plays_on_the_operator_port(self):
        """The denial is the adult rule, not a broken route: prove the same call
        succeeds for an unflagged link, or a regression that 404s everything would
        pass every test above."""
        link = self.source_id(self.post_id)
        status, _ = self.get(f"/api/v1/stream?id={link}", self.operator_port)
        self.assertIn(status, (200, 302), "operator debugging handle still works")

    def test_the_flagged_work_is_indistinguishable_from_absent_everywhere_public(self):
        total, ids = self.public_titles()
        self.assertNotIn(self.adult_id, ids)
        self.assertNotIn("Adult Diary", json.dumps(self.get("/api/v1/posts?limit=50",
                                                             self.public_port)[1]))
        status, body = self.get(f"/api/v1/posts/{self.adult_id}", self.public_port)
        self.assertEqual(status, 404, body)
        status, body = self.get(f"/api/m3u?id={self.adult_id}", self.public_port)
        self.assertEqual(status, 200)
        self.assertNotIn("#EXTINF", body, "a playlist may not carry one playable entry")

    # ── the operator panel may see the flag, and only the operator ───────────

    def test_the_bulk_dump_is_unreachable_from_the_public_port(self):
        status, _ = self.get("/api/data", self.public_port)
        self.assertEqual(status, 404, "the panel that shows the flag is not public")

    def test_the_operator_panel_lists_the_flagged_row_and_its_badge_data(self):
        # `stats=full` because this test is about the rows and the badge, and the
        # panel's default counters are the projection's stamp (null without one).
        status, body = self.get("/api/data?stats=full", self.operator_port)
        self.assertEqual(status, 200, body)
        payload = json.loads(body)
        listed = {row["id"]: row for row in payload["posts"]}
        self.assertIn(self.adult_id, listed,
                      "the audit surface must not pretend the row does not exist")
        self.assertEqual(int(listed[self.adult_id]["is_18_plus"]), 1)
        self.assertEqual(int(payload["stats"]["posts_adult"]), 1)
        self.assertEqual(int(payload["stats"]["posts_count"]),
                         self.one("SELECT COUNT(*) AS n FROM posts")["n"],
                         "the operator's scale counts every row it owns, flagged or not")

    def test_the_non_operator_payload_still_excludes_the_flagged_row(self):
        payload = viewer.fetch_database_payload(full=False)
        self.assertNotIn(self.adult_id, [row["id"] for row in payload["posts"]])

    # ── the row-level law reconciled at the work's key ──────────────────────

    def test_the_search_route_stops_serving_the_unflagged_twin_once_reconciled(self):
        key = self.one("SELECT canonical_key FROM posts WHERE id = ?",
                       (self.adult_id,))["canonical_key"]
        self.insert_twin(key, clean_title="Adult Diary")

        # The exposure, reproduced: every guard answers truthfully, because the row
        # the list filters was legitimately never flagged.
        total, ids = self.public_titles(query="Adult Diary")
        self.assertEqual(total, 1, "fixture failed to reproduce the measured leak")

        flipped = fast_fetch.reconcile_key_adult(self.db_path)
        self.assertEqual(flipped, 1)

        total, ids = self.public_titles(query="Adult Diary")
        self.assertEqual(total, 0)
        self.assertEqual(ids, [])
        total, _ = self.public_titles()
        self.assertEqual(total, self.one(
            "SELECT COUNT(*) AS n FROM posts WHERE COALESCE(is_18_plus, 0) = 0")["n"],
            "the unflagged fixture films stay listed")

    def test_the_merge_time_fold_hides_a_shared_key_twin_from_list_search_and_play(self):
        """Two titles, one `canonical_key`, one flagged: after reconciliation the public
        API serves neither — list, search, or stream.

        The reconciliation is the one a merge runs (`reconcile_adult_on_merge`), not a
        raw key-level MAX read at request time: a read-time MAX would also hide the twin
        of a flag no rule can reproduce, which is the 407-works regression pinned by the
        next test.
        """
        key = self.one("SELECT canonical_key FROM posts WHERE id = ?",
                       (self.adult_id,))["canonical_key"]
        twin_url = self.insert_twin(key, clean_title="Adult Diary")
        twin_id = self.one("SELECT id FROM posts WHERE url = ?", (twin_url,))["id"]
        with sqlite3.connect(self.db_path) as conn:
            release_id = conn.execute(
                "INSERT INTO releases (post_id, release_title, quality, source_site)"
                " VALUES (?, 'Adult Diary 720p', '720p', 'bolly4u')", (twin_id,)).lastrowid
            link_id = conn.execute(
                "INSERT INTO download_sources (release_id, service, resource_id,"
                " source_url, final_url) VALUES (?, 'pixeldrain', 'twin',"
                " 'https://bolly4u.example/dl/twin', 'https://pixeldrain.com/u/twin')",
                (release_id,)).lastrowid

        total, ids = self.public_titles(query="Adult Diary")
        self.assertEqual((total, ids), (1, [twin_id]),
                         "fixture failed to reproduce the shared-key exposure")
        self.assertFalse(redact.link_is_adult(link_id, self.db_path))

        with fast_fetch.get_db() as conn:
            folded = fast_fetch.apply_corroborated_adult_fold(
                conn, fast_fetch.corroborated_adult_exposures(conn))
        self.assertEqual(folded, 1)

        total, ids = self.public_titles(query="Adult Diary")
        self.assertEqual((total, ids), (0, []), "search still served the twin")
        total, ids = self.public_titles()
        self.assertNotIn(twin_id, ids, "the general list still served the twin")
        self.assertTrue(redact.link_is_adult(link_id, self.db_path),
                        "the folded row's link must not play")
        self.assertEqual(
            self.one("SELECT COUNT(*) AS n FROM adult_fold_journal")["n"], 1,
            "the flip must be journalled so --undo can reverse it")

    def test_an_asserted_only_flag_never_hides_its_twin(self):
        """The 407-works boundary, on the public surface.

        A stored flag that `is_adult_title()` cannot reproduce is a review candidate,
        not evidence: propagating it is how a catalog-wide MAX hid 407 mainstream works
        (measured 2026-10-30). The twin stays listed until the flag itself is resolved.
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO posts (url, slug, title, clean_title, year, content_type,"
                " source_site, is_18_plus, canonical_key)"
                " VALUES (?, ?, ?, ?, 2014, 'movie', ?, 1, ?)",
                ("https://ssrmovies.example/nenokkadine", "nenokkadine",
                 "1 - Nenokkadine (2014) South Indian Hindi Dubbed",
                 "1 - Nenokkadine", "ssrmovies", "1-nenokkadine-2014"))
            conn.execute(
                "INSERT INTO posts (url, slug, title, clean_title, year, content_type,"
                " source_site, is_18_plus, canonical_key)"
                " VALUES (?, ?, ?, ?, 2014, 'movie', ?, 0, ?)",
                ("https://moviezguru.example/nenokkadine", "nenokkadine-copy",
                 "1 - Nenokkadine (2014)", "1 - Nenokkadine", "moviezguru",
                 "1-nenokkadine_2014"))
        total, ids = self.public_titles(query="Nenokkadine")
        self.assertEqual(total, 1, "fixture: the disputed twin is public")

        with fast_fetch.get_db() as conn:
            folded = fast_fetch.apply_corroborated_adult_fold(
                conn, fast_fetch.corroborated_adult_exposures(conn))
        self.assertEqual(folded, 0, "an unreproducible flag must propagate to nobody")
        total, _ = self.public_titles(query="Nenokkadine")
        self.assertEqual(total, 1, "the twin was hidden on evidence the rule rejects")

    def test_a_second_site_cannot_write_a_public_copy_of_a_hidden_work(self):
        """The same film from another site lands on the flagged row, so the ingest
        path cannot re-create the exposure the backfill closed."""
        post_id = fast_fetch.save_scraped_data(
            media("moviesmela", "https://moviesmela.example/adult-diary-episodes/",
                  clean_title="Adult Diary", adult=0))
        self.assertEqual(post_id, self.adult_id,
                         "one work identity, one row — a page slug is not the identity")
        self.assertEqual(int(self.one(
            "SELECT is_18_plus FROM posts WHERE id = ?", (post_id,))["is_18_plus"]), 1,
            "an unflagged page cannot clear the flag the work already carries")
        self.assertEqual(self.public_titles(query="Adult Diary")[0], 0)

    def test_a_key_with_two_rows_refuses_an_arbitrary_merge(self):
        """The safety rule that predates this fix, kept honest: two rows sharing a
        key is an ambiguous identity, so the ingest raises instead of picking one and
        quietly making a third public copy."""
        key = self.one("SELECT canonical_key FROM posts WHERE id = ?",
                       (self.adult_id,))["canonical_key"]
        self.insert_twin(key, clean_title="Adult Diary")
        with self.assertRaises(ValueError):
            fast_fetch.save_scraped_data(
                media("moviesmela", "https://moviesmela.example/adult-diary-episodes/",
                      clean_title="Adult Diary", adult=0))
        rows = self.one("SELECT COUNT(*) AS n FROM posts")["n"]
        self.assertEqual(rows, 3, "the refused write added no row")


class ZeroDataLossTests(FixtureMixin):
    def setUp(self):
        self.make_ledger()

    def test_the_ledger_keeps_everything_the_public_stops_showing(self):
        row = self.one("SELECT source_site, url FROM posts WHERE id = ?", (self.post_id,))
        self.assertEqual(row["source_site"], "vegamovies")
        self.assertIn("vegamovies", row["url"])
        src = self.one("SELECT s.service, s.source_name, s.final_url, s.source_url, "
                       "s.resource_id FROM download_sources s "
                       "JOIN releases r ON r.id = s.release_id WHERE r.post_id = ?",
                       (self.post_id,))
        self.assertEqual(src["service"], "pixeldrain")
        self.assertIn("pixeldrain", src["final_url"])
        self.assertTrue(src["source_url"])
        rel = self.one("SELECT release_title, source_site, intermediate_url FROM releases "
                       "WHERE post_id = ?", (self.post_id,))
        self.assertEqual(rel["source_site"], "vegamovies")
        self.assertIn("vegamovies", rel["intermediate_url"])
        self.assertIn("pixeldrain", rel["release_title"].lower())
        self.assertIn("vegamovies", self.one(
            "SELECT title FROM posts WHERE id = ?", (self.post_id,))["title"].lower())

    def test_the_resolver_still_produces_a_real_url_for_our_own_handle(self):
        resolved = fast_fetch.resolve_live_source(self.source_id(self.post_id))
        self.assertTrue(resolved["success"], resolved)
        self.assertIn("pixeldrain", resolved["url"])

    def test_projection_publishes_the_same_catalog_minus_provenance(self):
        """The v2 read model must be clean *before* scrub, not because of it."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            catalog_v2.project(conn, verbose=False)
            browse = catalog_api.browse(conn, limit=50)
            self.assertEqual(redact.scrub(browse), browse,
                             "scrub should be a no-op on our own builders")
            self.assert_no_provenance(browse, "browse")
            work_id = browse["items"][0]["id"]
            detail = catalog_api.work_detail(conn, work_id=work_id)
            self.assertEqual(redact.scrub(detail), detail)
            self.assert_no_provenance(detail, "work_detail")
            release_id = detail["prints"][0]["release_id"]
            bundle = catalog_api.play_bundle(conn, release_id=release_id)
            self.assertEqual(redact.scrub(bundle), bundle,
                             "the failover ladder must not name a hoster either")
            self.assert_no_provenance(bundle, "play_bundle")
            self.assertTrue(bundle["candidates"], "and it must still hand out links")
            for link in bundle["candidates"]:
                self.assertTrue(link["stream_id"])
        finally:
            conn.close()

    def assert_no_provenance(self, payload, label):
        self.assertEqual(redact.provenance_keys(payload), [], label)
        self.assertEqual(redact.is_clean(payload, redact.site_needles(self.db_path)),
                         [], f"{label} leaks a known site or hoster name")

    def test_a_random_handle_that_spells_a_brand_is_not_a_leak(self):
        # A stream_id is base64 noise, and noise collides: on the real catalog the
        # only "site name" inside the quality ladder was a handle spelling `gmpg`.
        # Masking handles stops the scan crying wolf without hiding a real one.
        handle = redact.mint_token(4242, "test-secret")
        self.assertFalse(redact.is_clean(
            {"link": {"stream_id": handle,
                      "play_url": f"http://our.box/api/v1/stream?id={handle}"}}),
            "an opaque handle must not read as provenance")
        spelled = redact.minted_values({"link": {"stream_id": handle}})
        self.assertIn(handle, spelled)
        # A brand that is actually in the text still trips it.
        self.assertTrue(redact.is_clean({"label": "vegamovies Watch Online"},
                                        needles=["vegamovies"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
