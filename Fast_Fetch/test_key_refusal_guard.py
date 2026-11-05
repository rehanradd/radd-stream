#!/usr/bin/env python3
"""A `canonical_key` may only be stamped on a row whose own title and year name it.

Why this suite exists, in the two shapes it came from. `CROWN_KEY_CENSUS_13` §1 measured 164
keys that hold at least one row whose own title does not name the key — 19 of them flagged, so
the flag is a hiding verdict about somebody else's work: `a-perfect-murder_1998` carries
"Van Wilder UNRATED" (2002), `hi-zindagi_2025` carries "Maanaadu" (2021), `mathu-vadalara_2019`
carries "Robinhood" (2025). And §2 records the opposite shape, which the same metric counts and
a human does not: `kapatadhaari_2021` carries "Kabadadaari (2021) Dual Audio" — one film, two
transliterations. A rule that refuses the first must fold the second, or it hides legitimate
works on a spelling.

The write-time vector is the matched-previous-record path: `save_scraped_data` adopts the stored
row's key, then `MAX(is_18_plus, ?)` and `inherit_key_adult` propagate the flag across whatever
that key names. Every test below drives that path or the pure predicate beside it.

Offline: temp SQLite files via `fast_fetch.init_db()`, no network, no production catalog.

    python3 -S Fast_Fetch/test_key_refusal_guard.py
"""
from __future__ import annotations

import contextlib
import difflib
import io
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.resolve()))

import fast_fetch        # noqa: E402
import key_census        # noqa: E402


#: The census's different-work collisions: (key the row carries, the row's own title, its year)
COLLISIONS = [
    ("a-perfect-murder_1998", "Van Wilder UNRATED", 2002),
    ("hi-zindagi_2025", "Maanaadu (2021) (Hindi + Tamil) Action Thriller", 2021),
    ("mathu-vadalara_2019", "Robinhood (2025) (Hindi + Telugu)", 2025),
    ("thimiru-pudichavan_2018", "Thambi (My Brother Vicky) (2019)", 2019),
    ("finding-her-edge_2026", "Veerappan The Bandit King", 2020),
]
#: Same work, two spellings or two release names — these must fold, not split.
VARIANTS = [
    ("kapatadhaari_2021", "Download Kabadadaari (2021) Dual Audio", 2021),
    ("chor-bazaar_2023", "SChor Bazaar", 2023),
    ("aaj-ka-khiladi_2020", "Ninnu Kori (Aaj Ka Khiladi)", 2017),
    ("dune-part-two_2024", "Dune: Part Two (2024) 4K BluRay Hindi", 2024),
]
#: Title fails, year holds — the conjunction the rule requires, so no refusal. DOCUMENTED LIMIT.
YEAR_CARRIES_IT = [
    ("100-bullets_2016", "Frank Phoenix UNRATED", 2016),
    ("7-aum-arivu_2011", "Chennai vs China", 2011),
]


class FixtureCase(unittest.TestCase):
    """A temp catalog built by the real `init_db`, so the schema is not a fixture's guess."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "census.db"
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            """
            CREATE TABLE posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT UNIQUE NOT NULL,
                slug TEXT, title TEXT, clean_title TEXT, year INTEGER,
                content_type TEXT DEFAULT 'movie',
                is_18_plus INTEGER DEFAULT 0,
                canonical_key TEXT
            );
            """
        )

    def tearDown(self):
        self.conn.close()
        self.temp_dir.cleanup()

    def seed(self, *, url, title, clean_title=None, year=None, key, flag=0):
        self.conn.execute(
            "INSERT INTO posts (url, slug, title, clean_title, year, content_type,"
            " is_18_plus, canonical_key) VALUES (?, ?, ?, ?, ?, 'movie', ?, ?)",
            (url, url.rstrip("/").split("/")[-1], title, clean_title or title, year,
             flag, key),
        )
        self.conn.commit()
        return self.conn.execute(
            "SELECT id FROM posts WHERE url = ?", (url,)).fetchone()["id"]

    def key_of(self, post_id):
        return self.conn.execute(
            "SELECT canonical_key FROM posts WHERE id = ?", (post_id,)).fetchone()["canonical_key"]


class PredicateTests(FixtureCase):
    """`canonical_key_corroborates` on the rows the census named, both directions."""

    def test_different_work_collisions_are_refused(self):
        for key, title, year in COLLISIONS:
            with self.subTest(key=key):
                corroborated, why = fast_fetch.canonical_key_corroborates(key, [title], year=year)
                self.assertFalse(corroborated, why)
                self.assertTrue(why, "a refusal must arrive with its evidence, not silently")

    def test_spelling_and_alias_variants_are_folded(self):
        for key, title, year in VARIANTS:
            with self.subTest(key=key):
                self.assertTrue(
                    fast_fetch.canonical_key_corroborates(key, [title], year=year)[0],
                    "a spelling variant must not split a work into two keys")

    def test_year_agreement_alone_is_not_a_refusal(self):
        # Deliberate limit, stated so nobody reads the guard as covering the whole 164:
        # these rows fail on title and pass on year, so the conjunction does not fire.
        for key, title, year in YEAR_CARRIES_IT:
            with self.subTest(key=key):
                corroborated, why = fast_fetch.canonical_key_corroborates(key, [title], year=year)
                self.assertTrue(corroborated)
                self.assertIn("year", why)

    def test_exact_title_agrees_with_its_own_key(self):
        self.assertTrue(fast_fetch.canonical_key_corroborates(
            "inception_2010", ["Inception"], year=2010)[0])

    def test_degenerate_keys_make_no_claim_and_are_never_refused(self):
        for key in ("", None, "unknown", "  "):
            with self.subTest(key=key):
                self.assertTrue(fast_fetch.canonical_key_corroborates(
                    key, ["Some Other Film"], year=1999)[0])

    def test_the_degenerate_key_exemption_is_the_exact_unknown_bucket(self):
        """The exemption stops at `unknown`, exactly like `inherit_key_adult`'s own boundary.

        `''` and `unknown` are the shared buckets every titleless payload lands in, so
        neither may be contradicted into a re-file. `unknown_2020` is a different shape: it
        makes a year claim, it is not the bucket `inherit_key_adult` refuses to propagate
        from, and nothing in the key builder can produce it (`generate_canonical_key` of a
        boilerplate-only title yields `_2020`, not `unknown_2020`). Pinning the boundary in
        both directions is what makes M5's equivalence argument checkable rather than a
        claim about the code.
        """
        for bucket in ("unknown", ""):
            with self.subTest(bucket=bucket):
                corroborated, why = fast_fetch.canonical_key_corroborates(
                    bucket, ["A Different Work"], year=1999)
                self.assertTrue(corroborated, why)
                filed, refused = fast_fetch.guard_canonical_key(
                    bucket, "A Different Work", year=1999)
                self.assertEqual(filed, bucket)
                self.assertIsNone(refused)
        self.assertFalse(fast_fetch.canonical_key_corroborates(
            "unknown_2020", ["A Different Work"], year=1999)[0],
            "a key that claims a year is not the shared bucket and is judged like any other")

    def test_a_yearless_key_is_not_contradicted_by_a_year(self):
        # `black-mirror` names no year, so a 2019 row under it fails on title only.
        self.assertTrue(fast_fetch.canonical_key_corroborates(
            "black-mirror", ["A Different Work"], year=2019)[0])

    def test_a_row_with_no_title_evidence_is_never_refused(self):
        for titles in ([], [None], [""], ["   "]):
            with self.subTest(titles=titles):
                self.assertTrue(fast_fetch.canonical_key_corroborates(
                    "hi-zindagi_2025", titles, year=2021)[0])

    def test_a_row_with_no_year_is_never_refused(self):
        self.assertTrue(fast_fetch.canonical_key_corroborates(
            "hi-zindagi_2025", ["Maanaadu (2021)"], year=None)[0])

    def test_a_non_numeric_year_is_not_read_as_agreement_or_refusal(self):
        # A garbage year column must not become evidence that contradicts the key: the
        # rule refuses only on measured disagreement.
        for junk in ("n/a", "0", "?", "unknown"):
            with self.subTest(year=junk):
                self.assertTrue(fast_fetch.canonical_key_corroborates(
                    "hi-zindagi_2025", ["Maanaadu"], year=junk)[0])

    def test_key_year_and_title_parts_are_parsed_off_the_documented_shape(self):
        self.assertEqual(fast_fetch.key_year("aaj-ka-khiladi_2020"), 2020)
        self.assertIsNone(fast_fetch.key_year("black-mirror"))
        self.assertEqual(fast_fetch.key_title_tokens("hi-zindagi_2025"),
                         frozenset({"hi", "zindagi"}))

    def test_title_token_sets_keep_the_alias_the_key_builder_drops(self):
        sets = fast_fetch._title_token_sets("Ninnu Kori (Aaj Ka Khiladi)")
        self.assertIn(frozenset({"ninnu", "kori"}), sets)
        self.assertIn(frozenset({"aaj", "ka", "khiladi"}), sets,
                      "the bracketed release name is evidence; generate_canonical_key drops it")

    def test_the_threshold_sits_in_the_measured_gap(self):
        """KEY_TITLE_AGREE_RATIO is a claim about data, and it is checked as one.

        Re-measured here from the fixture rows, so if the two populations ever overlap the
        suite says so instead of quietly trusting 0.50. The floor is taken on the rows the
        ratio arm actually decides — *Kabadadaari* against `kapatadhaari_2021` — because the
        alias rows fold on the subset arm and would score 0.00 while still being correct.
        """
        def score(key, title):
            tokens = " ".join(sorted(fast_fetch.key_title_tokens(key)))
            return max(
                difflib.SequenceMatcher(None, " ".join(sorted(own)), tokens).ratio()
                for own in fast_fetch._title_token_sets(title))

        refuse_ceiling = max(score(key, title) for key, title, _y in COLLISIONS)
        agree_floor = min(score(key, title) for key, title, _y in VARIANTS
                          if key == "kapatadhaari_2021")
        self.assertLess(refuse_ceiling, fast_fetch.KEY_TITLE_AGREE_RATIO,
                        "a different-work collision scored at or above the threshold")
        self.assertGreater(agree_floor, fast_fetch.KEY_TITLE_AGREE_RATIO,
                           "the threshold would now split a measured spelling variant")
        self.assertLess(refuse_ceiling, agree_floor,
                        "the two populations are no longer separated: re-measure the rule")


class GuardDecisionTests(unittest.TestCase):
    """`guard_canonical_key` only ever replaces a key it refused."""

    def test_a_refused_key_is_replaced_by_the_rows_own_derived_key(self):
        filed, refused = fast_fetch.guard_canonical_key(
            "a-perfect-murder_1998", "Van Wilder", title="Van Wilder UNRATED", year=2002)
        self.assertEqual(filed, "van-wilder_2002")
        self.assertEqual(refused[0], "a-perfect-murder_1998")
        self.assertIn("2002", refused[1])

    def test_an_agreeing_row_keeps_the_adopted_key_and_journals_nothing(self):
        filed, refused = fast_fetch.guard_canonical_key(
            "kapatadhaari_2021", "Kabadadaari", title="Kabadadaari (2021)", year=2021)
        self.assertEqual(filed, "kapatadhaari_2021")
        self.assertIsNone(refused)

    def test_a_degenerate_candidate_key_is_passed_through_unchanged(self):
        # The guard must not turn a missing stored key into `unknown`, and must not
        # invent one: that would re-key rows the adoption site deliberately leaves alone.
        for candidate in (None, "", "unknown"):
            with self.subTest(candidate=candidate):
                filed, refused = fast_fetch.guard_canonical_key(
                    candidate, "Some Film", year=2020)
                self.assertEqual(filed, candidate)
                self.assertIsNone(refused)

    def test_a_refusal_with_no_usable_self_derived_key_keeps_the_stored_key(self):
        # clean_title of pure boilerplate derives "_2024", which names no work and is a
        # worse home than the foreign key: keep the foreign key, refuse nothing.
        filed, refused = fast_fetch.guard_canonical_key(
            "100-bullets_2016", "1080p", title="1080p", year=2024)
        self.assertEqual(filed, "100-bullets_2016")
        self.assertIsNone(refused)

    def test_the_fallback_slug_is_used_when_the_title_derives_nothing(self):
        filed, refused = fast_fetch.guard_canonical_key(
            "100-bullets_2016", "1080p", title="1080p", year=2024,
            fallback="Some-Other-Page")
        self.assertEqual(filed, "100-bullets_2016")
        self.assertIsNone(refused, "a slug-derived key is not title evidence either way")


@contextlib.contextmanager
def temp_catalog():
    temp = tempfile.TemporaryDirectory()
    path = Path(temp.name) / "gate.db"
    with patch.object(fast_fetch, "DB_PATH", path), \
            patch.object(fast_fetch, "fetch_cinemeta_metadata", return_value=None):
        fast_fetch.init_db()
        yield path
    temp.cleanup()


def payload(site, url, *, title, clean_title, year=None, imdb_id=None, flag=0):
    return {
        "url": url,
        "slug": url.rstrip("/").split("/")[-1],
        "title": title,
        "clean_title": clean_title,
        "year": year,
        "content_type": "movie",
        "seasons": None,
        "poster_url": None,
        "backdrop_urls": None,
        "imdb_rating": None,
        "genres": None,
        "synopsis": None,
        "is_18_plus": flag,
        "is_animated": 0,
        "source_site": site,
        "industry": "South India",
        "country": "India",
        "language": "Hindi",
        "canonical_key": fast_fetch.generate_canonical_key(clean_title, year),
        "tmdb_id": None,
        "imdb_id": imdb_id,
        "releases": [{
            "release_title": f"{clean_title} {year} 1080p",
            "quality": "1080p", "codec": "x264", "size": "1GB",
            "languages": "Hindi", "season": None, "episode": None,
            "intermediate_url": f"https://{site}.example/release",
            "sources": [{
                "source_name": "Example CDN", "service": "test-service",
                "resource_id": f"{site}-id",
                "source_url": f"https://{site}.example/source",
                "final_url": f"https://cdn.example/{site}", "is_temporary": 0,
            }],
        }],
    }


class WritePathTests(unittest.TestCase):
    """The stamp site in `save_scraped_data`: adopt, corroborate, or refuse and journal."""

    def setUp(self):
        self._temp = temp_catalog()
        self.db_path = self._temp.__enter__()
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row

    def tearDown(self):
        self.conn.close()
        self._temp.__exit__(None, None, None)

    def scalar(self, sql, params=()):
        return self.conn.execute(sql, params).fetchone()[0]

    def journal(self):
        if self.scalar("SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
                       " AND name='key_refusal_journal'") == 0:
            return []
        return self.conn.execute("SELECT * FROM key_refusal_journal ORDER BY post_id").fetchall()

    def test_a_mis_stamped_row_is_refused_and_refiled_under_its_own_title(self):
        # The historical state: a row carrying someone else's key and a NULL year, which
        # is exactly what let the flag cross onto `a-perfect-murder_1998`.
        legit = fast_fetch.save_scraped_data(payload(
            "site_a", "https://site-a.example/a-perfect-murder-1998/",
            title="A Perfect Murder (1998)", clean_title="A Perfect Murder", year=1998),
            enrich_metadata=False)
        bad = fast_fetch.save_scraped_data(payload(
            "site_b", "https://site-b.example/van-wilder-unrated/",
            title="Van Wilder UNRATED", clean_title="Van Wilder", year=None, flag=1),
            enrich_metadata=False)
        self.conn.execute("UPDATE posts SET canonical_key = 'a-perfect-murder_1998'"
                          " WHERE id = ?", (bad,))
        self.conn.commit()

        # The same page re-ingested, this time with its own year read off the page.
        again = fast_fetch.save_scraped_data(payload(
            "site_b", "https://site-b.example/van-wilder-unrated/",
            title="Van Wilder (2002) UNRATED 18+", clean_title="Van Wilder", year=2002,
            flag=1), enrich_metadata=False)

        self.assertEqual(again, bad, "the row was kept, not deleted or duplicated")
        self.assertEqual(self.key_of(bad), "van-wilder_2002")
        self.assertEqual(self.key_of(legit), "a-perfect-murder_1998",
                         "the sibling was not re-keyed by this ingest")
        entries = self.journal()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["refused_key"], "a-perfect-murder_1998")
        self.assertEqual(entries[0]["filed_under"], "van-wilder_2002")
        self.assertEqual(entries[0]["post_id"], bad)
        self.assertTrue(entries[0]["evidence"], "the refusal must say why")

    def key_of(self, post_id):
        return self.conn.execute("SELECT canonical_key FROM posts WHERE id = ?",
                                 (post_id,)).fetchone()["canonical_key"]

    def test_the_flag_does_not_cross_the_refused_key_onto_the_legitimate_work(self):
        # The point of the whole rule: before it, MAX(is_18_plus) + inherit_key_adult hid
        # "A Perfect Murder" on the verdict of a Van Wilder page.
        legit = fast_fetch.save_scraped_data(payload(
            "site_a", "https://site-a.example/a-perfect-murder-1998/",
            title="A Perfect Murder (1998)", clean_title="A Perfect Murder", year=1998),
            enrich_metadata=False)
        bad = fast_fetch.save_scraped_data(payload(
            "site_b", "https://site-b.example/van-wilder-unrated/",
            title="Van Wilder UNRATED", clean_title="Van Wilder", year=None, flag=1),
            enrich_metadata=False)
        self.conn.execute("UPDATE posts SET canonical_key = 'a-perfect-murder_1998'"
                          " WHERE id = ?", (bad,))
        self.conn.commit()
        fast_fetch.save_scraped_data(payload(
            "site_b", "https://site-b.example/van-wilder-unrated/",
            title="Van Wilder (2002) UNRATED 18+", clean_title="Van Wilder", year=2002,
            flag=1), enrich_metadata=False)

        self.assertEqual(self.scalar("SELECT is_18_plus FROM posts WHERE id = ?", (legit,)), 0,
                         "a legitimate mainstream work was hidden by a foreign flag")
        self.assertEqual(self.scalar("SELECT is_18_plus FROM posts WHERE id = ?", (bad,)), 1,
                         "the adult row must stay flagged under its own key")

    def test_the_same_ingest_without_the_guard_does_hide_the_twin(self):
        """Counterfactual, so the green above is the rule's and not the fixture's.

        Neuter `guard_canonical_key` to the identity and the exposure reappears; if this
        test passes too, the write path is not exercising the guard at all.
        """
        with patch.object(fast_fetch, "guard_canonical_key",
                          lambda candidate, *a, **k: (candidate, None)):
            legit = fast_fetch.save_scraped_data(payload(
                "site_a", "https://site-a.example/a-perfect-murder-1998/",
                title="A Perfect Murder (1998)", clean_title="A Perfect Murder", year=1998),
                enrich_metadata=False)
            bad = fast_fetch.save_scraped_data(payload(
                "site_b", "https://site-b.example/van-wilder-unrated/",
                title="Van Wilder UNRATED", clean_title="Van Wilder", year=None, flag=1),
                enrich_metadata=False)
            self.conn.execute("UPDATE posts SET canonical_key = 'a-perfect-murder_1998'"
                              " WHERE id = ?", (bad,))
            self.conn.commit()
            fast_fetch.save_scraped_data(payload(
                "site_b", "https://site-b.example/van-wilder-unrated/",
                title="Van Wilder (2002) UNRATED 18+", clean_title="Van Wilder", year=2002,
                flag=1), enrich_metadata=False)
            self.assertEqual(self.key_of(bad), "a-perfect-murder_1998")
            self.assertEqual(self.scalar("SELECT is_18_plus FROM posts WHERE id = ?", (legit,)), 1,
                             "the mutant failed to reproduce the defect the guard prevents")
            self.assertEqual(self.journal(), [],
                             "a neutered guard must not leave a journal row")

    def test_a_wrong_id_match_on_a_spelling_variant_shares_one_key_and_writes_no_journal(self):
        legit = fast_fetch.save_scraped_data(payload(
            "site_a", "https://site-a.example/kapatadhaari-2021/",
            title="Kapatadhaari 2021 UNCUT Dual Audio Hindi", clean_title="Kapatadhaari",
            year=2021, imdb_id="tt1513374"), enrich_metadata=False)
        twin = fast_fetch.save_scraped_data(payload(
            "site_b", "https://site-b.example/kabadadaari-2021-dual-audio/",
            title="Download Kabadadaari (2021) Dual Audio", clean_title="Kabadadaari",
            year=2021, imdb_id="tt1513374"), enrich_metadata=False)
        self.assertEqual(twin, legit, "one film, two spellings, one ledger row")
        self.assertEqual(self.key_of(legit), "kapatadhaari_2021")
        self.assertEqual(self.journal(), [],
                         "folding a variant is not a refusal; the journal is for refusals only")

    def test_an_ingest_that_agrees_writes_no_journal_row(self):
        fast_fetch.save_scraped_data(payload(
            "site_a", "https://site-a.example/inception-2010/",
            title="Inception (2010)", clean_title="Inception", year=2010),
            enrich_metadata=False)
        fast_fetch.save_scraped_data(payload(
            "site_a", "https://site-a.example/inception-2010/",
            title="Inception (2010) 720p BluRay", clean_title="Inception", year=2010),
            enrich_metadata=False)
        self.assertEqual(self.journal(), [])

    def test_the_journal_table_is_created_on_first_refusal_only(self):
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
                                     " AND name='key_refusal_journal'"), 0)
        fast_fetch.save_scraped_data(payload(
            "site_a", "https://site-a.example/inception-2010/",
            title="Inception (2010)", clean_title="Inception", year=2010),
            enrich_metadata=False)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
                                     " AND name='key_refusal_journal'"), 0,
                         "an unused journal must not be created by every ingest")

    def test_a_refused_row_keeps_its_links(self):
        bad = fast_fetch.save_scraped_data(payload(
            "site_b", "https://site-b.example/van-wilder-unrated/",
            title="Van Wilder UNRATED", clean_title="Van Wilder", year=None, flag=1),
            enrich_metadata=False)
        self.conn.execute("UPDATE posts SET canonical_key = 'a-perfect-murder_1998'"
                          " WHERE id = ?", (bad,))
        self.conn.commit()
        fast_fetch.save_scraped_data(payload(
            "site_b", "https://site-b.example/van-wilder-unrated/",
            title="Van Wilder (2002) UNRATED 18+", clean_title="Van Wilder", year=2002,
            flag=1), enrich_metadata=False)
        self.assertGreaterEqual(
            self.scalar("SELECT COUNT(*) FROM releases WHERE post_id = ?", (bad,)), 1,
            "a re-file must not orphan the row's releases")


class CensusTests(FixtureCase):
    """`census_key_refusals` reports the two metrics apart and writes nothing."""

    def fixture(self):
        for key, title, year in COLLISIONS:
            self.seed(url=f"https://x.example/{key}/", title=title, clean_title=title,
                      year=year, key=key)
        for key, title, year in YEAR_CARRIES_IT:
            self.seed(url=f"https://y.example/{key}/", title=title, clean_title=title,
                      year=year, key=key)
        for key, title, year in VARIANTS:
            self.seed(url=f"https://z.example/{key}/", title=title, clean_title=title,
                      year=year, key=key, flag=1)
        self.seed(url="https://w.example/orphan/", title="No Key Film",
                  clean_title="No Key Film", year=2020, key=None)

    def test_census_separates_the_crown_metric_from_the_rules_own(self):
        self.fixture()
        report = fast_fetch.census_key_refusals(self.conn)
        self.assertEqual(report["rows_with_key"], len(COLLISIONS) + len(YEAR_CARRIES_IT)
                         + len(VARIANTS), "the row-less fixture was counted")
        self.assertEqual(report["title_only_disagree"], len(COLLISIONS) + len(YEAR_CARRIES_IT),
                         "crown's title-only count must include the year-carried rows")
        self.assertEqual(report["would_refuse"], len(COLLISIONS))
        self.assertLess(report["would_refuse"], report["title_only_disagree"],
                        "the two metrics collapsed into one number")
        self.assertEqual(report["keys_affected"], sorted(k for k, _t, _y in COLLISIONS))

    def test_census_counts_the_flagged_subset_separately(self):
        self.fixture()
        report = fast_fetch.census_key_refusals(self.conn)
        self.assertEqual(report["would_refuse_flagged"], 0)
        self.conn.execute("UPDATE posts SET is_18_plus = 1 WHERE canonical_key = ?",
                          ("hi-zindagi_2025",))
        self.conn.commit()
        self.assertEqual(fast_fetch.census_key_refusals(self.conn)["would_refuse_flagged"], 1)

    def test_census_covers_nothing_outside_keyed_rows(self):
        self.seed(url="https://n.example/x/", title="Loose", clean_title="Loose",
                  year=2000, key=None)
        self.assertEqual(fast_fetch.census_key_refusals(self.conn)["rows_with_key"], 0)

    def test_census_writes_nothing(self):
        self.fixture()
        before = self.conn.execute(
            "SELECT id, canonical_key, is_18_plus FROM posts ORDER BY id").fetchall()
        fast_fetch.census_key_refusals(self.conn)
        after = self.conn.execute(
            "SELECT id, canonical_key, is_18_plus FROM posts ORDER BY id").fetchall()
        self.assertEqual([tuple(r) for r in before], [tuple(r) for r in after])
        self.assertIsNone(self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table'"
            " AND name='key_refusal_journal'").fetchone(),
            "a census that creates its journal is not a census")

    def test_census_sample_limit_is_honoured(self):
        self.fixture()
        self.assertEqual(len(fast_fetch.census_key_refusals(self.conn, sample_limit=2)["samples"]), 2)
        self.assertEqual(len(fast_fetch.census_key_refusals(self.conn, sample_limit=99)["samples"]),
                         len(COLLISIONS))

    def test_census_samples_carry_the_evidence_they_were_judged_on(self):
        self.fixture()
        for sample in fast_fetch.census_key_refusals(self.conn)["samples"]:
            self.assertTrue(sample["evidence"])
            self.assertIn(sample["refused_key"], sample["evidence"])
            self.assertNotEqual(sample["refused_key"], sample["filed_under"])

    def test_the_non_vacuous_floor(self):
        """The refusal arm ran on this fixture: a suite that measured nothing must not pass."""
        self.fixture()
        report = fast_fetch.census_key_refusals(self.conn)
        self.assertGreater(report["would_refuse"], 0,
                           "the fixture stopped exercising the refusal arm")
        self.assertEqual(
            report["title_fails_but_year_or_no_self_key_carries_it"],
            len(YEAR_CARRIES_IT),
            "the year-carried rows are kept, and must be counted as kept")


class CensusCliTests(FixtureCase):
    """`key_census.py` is read-only, refuses --apply, and prints the metric names."""

    def setUp(self):
        super().setUp()
        self.seed(url="https://x.example/a/", title="Van Wilder UNRATED",
                  clean_title="Van Wilder UNRATED", year=2002, key="a-perfect-murder_1998",
                  flag=1)
        self.seed(url="https://x.example/b/", title="A Perfect Murder",
                  clean_title="A Perfect Murder", year=1998, key="a-perfect-murder_1998")

    def test_census_flag_reports_both_metrics(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = key_census.main([str(self.db_path), "--census"])
        text = out.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("title fails to name its key", text)
        self.assertIn("of which the guard refuses", text)
        self.assertIn("CROWN_KEY_CENSUS_13", text,
                      "the metric difference must travel with the number")

    def test_apply_is_refused_out_loud_and_changes_nothing(self):
        before = self.conn.execute("SELECT id, canonical_key FROM posts ORDER BY id").fetchall()
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            rc = key_census.main([str(self.db_path), "--apply"])
        self.assertEqual(rc, 2)
        self.assertIn("REFUSED", err.getvalue())
        after = self.conn.execute("SELECT id, canonical_key FROM posts ORDER BY id").fetchall()
        self.assertEqual([tuple(r) for r in before], [tuple(r) for r in after])

    def test_the_connection_cannot_write_even_in_principle(self):
        conn = key_census.connect_read_only(self.db_path)
        try:
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute("UPDATE posts SET canonical_key = 'vandalized' WHERE id = 1")
        finally:
            conn.close()

    def test_json_output_is_parseable_and_keys_affected_is_a_list(self):
        import json
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            key_census.main([str(self.db_path), "--json"])
        report = json.loads(out.getvalue())
        self.assertIsInstance(report["keys_affected"], list)
        self.assertFalse(report["writable"])


class ArmFailabilityTests(unittest.TestCase):
    """Each arm of the conjunction is required: mutate it, and the refusals go (task #52)."""

    def fixture(self):
        rows = [(k, t, y) for k, t, y in COLLISIONS]
        return rows

    def refusals(self):
        return [k for k, t, y in self.fixture()
                if not fast_fetch.canonical_key_corroborates(k, [t], year=y)[0]]

    def test_the_title_arm_is_load_bearing(self):
        self.assertEqual(len(self.refusals()), len(COLLISIONS))
        with patch.object(fast_fetch, "_titles_agree", lambda *a, **k: True):
            self.assertEqual(self.refusals(), [],
                             "with agreement forced the rule refuses nothing, so the arm decided")

    def test_the_year_arm_is_load_bearing(self):
        with patch.object(fast_fetch, "key_year", lambda *a, **k: None):
            self.assertEqual(self.refusals(), [],
                             "a key that claims no year cannot be contradicted")

    def test_the_threshold_is_load_bearing_on_the_title_arm(self):
        """Mutate the threshold and both measured populations move, in opposite directions.

        Tested through `_titles_agree` rather than the whole conjunction, because a variant
        row also carries a corroborating year, and a conjunction test at ratio 1.0 would be
        measuring the year arm and calling it the threshold.
        """
        variant_tokens = fast_fetch.key_title_tokens("kapatadhaari_2021")
        variant_sets = fast_fetch._title_token_sets(
            "Download Kabadadaari (2021) Dual Audio")
        collision_tokens = fast_fetch.key_title_tokens("hi-zindagi_2025")
        collision_sets = fast_fetch._title_token_sets(
            "Maanaadu (2021) (Hindi + Tamil) Action Thriller")
        self.assertTrue(fast_fetch._titles_agree(variant_tokens, variant_sets))
        self.assertFalse(fast_fetch._titles_agree(collision_tokens, collision_sets))
        with patch.object(fast_fetch, "KEY_TITLE_AGREE_RATIO", 1.0):
            self.assertFalse(fast_fetch._titles_agree(variant_tokens, variant_sets),
                             "at ratio 1 the spelling variant splits: the tolerance is the threshold's")
        with patch.object(fast_fetch, "KEY_TITLE_AGREE_RATIO", 0.0):
            self.assertTrue(fast_fetch._titles_agree(collision_tokens, collision_sets),
                            "at ratio 0 a collision folds: the refusals were the threshold's")
        with patch.object(fast_fetch, "KEY_TITLE_AGREE_RATIO", 0.0):
            self.assertEqual(self.refusals(), [],
                             "with agreement forced the rule refuses nothing")

    def test_the_alias_arm_is_load_bearing(self):
        key, title, year = "aaj-ka-khiladi_2020", "Ninnu Kori (Aaj Ka Khiladi)", 2017
        self.assertTrue(fast_fetch.canonical_key_corroborates(key, [title], year=year)[0])
        with patch.object(fast_fetch, "_TITLE_ALIAS_SPLIT", __import__("re").compile(r"(?!)")):
            self.assertFalse(fast_fetch.canonical_key_corroborates(key, [title], year=year)[0],
                             "drop the alias reading and a same-work row looks like a collision")


if __name__ == "__main__":
    print("fixture: %s (offline, temp SQLite only — no network, no production catalog)"
          % Path(__file__).name)
    unittest.main(verbosity=2)
