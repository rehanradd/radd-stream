#!/usr/bin/env python3
"""The adult flag may propagate only across evidence the shared rule still reproduces.

Why this suite exists, in one measured number: on the live catalog 2026-10-30,
10,816 of 15,068 stored flags could not be re-derived from the row's own text by
`fast_fetch.is_adult_title()`. They are legacy importer verdicts, and the works they name
are mostly mainstream — *1 – Nenokkadine* (2014), *118* (2019), *24* (2016),
*18 Pages* (2022), every one of them flagged on dubbed-release vocabulary. 3,490 publicly
served rows sat in a `(clean_title, year)` group with one of those disputed flags, so the
cross-key fold this repository was about to run would have hidden 3,490 mostly-clean works
to catch 12 real ones. Each test below guards one direction of that error: the 12 must go,
the 3,490 must not.

The fold's one production consumer is the merge: a staging vault declares `canonical_key`
PRIMARY KEY/UNIQUE, so a twin cannot exist inside one database, and the exposure is only
created when two sites' rows meet in the unified catalog (`merge_catalogs.merge_site_db`
runs `reconcile_adult_on_merge`). This suite exercises the same functions directly.

Offline: temp SQLite files, one small `posts` table built here, no network, no catalog.

    python3 -S Fast_Fetch/test_adult_corroborated_fold.py
"""
from __future__ import annotations

import contextlib
import io
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.resolve()))

import backfill_adult_key   # noqa: E402
import fast_fetch           # noqa: E402
import redact               # noqa: E402

#: Every fixture is a `(title, clean_title)` pair. The evidence lives in `title`, because
#: that is where a scraper saw it: the verdict came off the raw page title, and the stored
#: clean title says nothing by itself.
CORROBORATED = ("Wife Office Boss (2026) 18+ Hindi Dubbed", "Wife Office Boss")
#: Distribution vocabulary only — no strong token anywhere, so the rule rejects it.
SUGGESTION_ONLY = ("Wife Office Boss (2026) UNCUT Dual Audio Hindi", "Wife Office Boss")
#: The *Nenokkadine* shape: a South Indian dub, flagged, and not by anything on this list.
DISPUTED = ("1 - Nenokkadine (2014) South Indian Hindi Dubbed", "1 - Nenokkadine")

POST_DDL = """
CREATE TABLE posts (
    id INTEGER PRIMARY KEY,
    title TEXT, clean_title TEXT, slug TEXT, url TEXT,
    source_site TEXT, year TEXT,
    canonical_key TEXT,
    is_18_plus INTEGER DEFAULT 0
)
"""


class Fixture(unittest.TestCase):
    """A temp catalog carrying the columns the fold reads, and nothing else."""

    def setUp(self):
        handle, self.path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute(POST_DDL)
        self.add(1, *CORROBORATED, site="hindilinks4u", year="2026",
                 key="wife-office-boss-2026", flag=1)

    def tearDown(self):
        self.conn.close()
        os.unlink(self.path)

    def add(self, post_id, title, clean_title, *, site, year, key, flag,
            slug=None, url=None):
        slug = slug or key
        self.conn.execute(
            "INSERT INTO posts (id, title, clean_title, slug, url, source_site,"
            " year, canonical_key, is_18_plus) VALUES (?,?,?,?,?,?,?,?,?)",
            (post_id, title, clean_title, slug,
             url or "https://%s.example/%s" % (site, slug),
             site, year, key, flag))
        self.conn.commit()

    def flag_of(self, post_id):
        return int(self.conn.execute("SELECT is_18_plus FROM posts WHERE id = ?",
                                     (post_id,)).fetchone()[0])

    def public_total(self):
        return int(self.conn.execute(
            "SELECT COUNT(*) FROM posts WHERE %s" % redact.adult_clause("posts")
        ).fetchone()[0])

    def journal(self):
        return self.conn.execute(
            "SELECT post_id, source_post_id, evidence FROM adult_fold_journal"
            " ORDER BY post_id").fetchall()


class RuleAgreementTests(unittest.TestCase):
    """The gate itself: which verdicts may be multiplied across siblings."""

    def row(self, title, clean_title=None, slug="x", site="bolly4u"):
        return {"clean_title": clean_title if clean_title is not None else title,
                "title": title, "slug": slug, "url": "https://x.example/" + slug,
                "source_site": site}

    def test_a_strong_token_in_the_stored_title_reproduces(self):
        self.assertTrue(fast_fetch.adult_rule_agrees(self.row(*CORROBORATED)))

    def test_the_clean_title_alone_is_not_required_to_carry_it(self):
        """`save_scraped_data` re-derives from `clean_title or title` and so loses what a
        cleaner stripped out of `clean_title`. This gate reads every text the row owns."""
        self.assertTrue(fast_fetch.adult_rule_agrees(
            self.row(CORROBORATED[0], CORROBORATED[1])))

    def test_dubbed_release_vocabulary_does_not_reproduce(self):
        """The false-positive class that made this gate necessary."""
        self.assertFalse(fast_fetch.adult_rule_agrees(
            self.row(*DISPUTED, slug="1-nenokkadine-2014-south-indian-hindi-dubbed-movie")))

    def test_distribution_words_alone_do_not_reproduce(self):
        self.assertFalse(fast_fetch.adult_rule_agrees(self.row(*SUGGESTION_ONLY)))

    def test_site_evidence_is_currently_no_evidence_at_all(self):
        """Characterization: `ADULT_SOURCE_SITES` is empty, so `source_site` corroborates
        nothing. If a lane ever fills that set, propagation gains a witness and the live
        provenance numbers above need re-measuring, not just re-running."""
        self.assertEqual(len(fast_fetch.ADULT_SOURCE_SITES), 0)
        self.assertFalse(fast_fetch.adult_rule_agrees(
            self.row("Some Plain Film", slug="some-plain-film")))


class WorkIdentityTests(unittest.TestCase):
    def test_title_and_year_group_across_keys(self):
        row = {"clean_title": " Puli ", "title": "Puli (2015) 18+", "year": 2015}
        self.assertEqual(fast_fetch.work_identity(row), ("puli", "2015"))

    def test_a_missing_year_is_not_an_identity(self):
        for year in (None, "", "two thousand fifteen"):
            self.assertIsNone(fast_fetch.work_identity(
                {"clean_title": "Vikram", "title": "Vikram", "year": year}))

    def test_an_empty_title_is_not_an_identity(self):
        self.assertIsNone(fast_fetch.work_identity(
            {"clean_title": "   ", "title": "", "year": "2020"}))

    def test_the_title_is_normalized_but_not_stemmed(self):
        self.assertEqual(fast_fetch.work_identity(
            {"clean_title": "The Duke", "title": None, "year": "2025"})[0], "the duke")


class ExposureTests(Fixture):
    def test_one_key_hides_its_sibling(self):
        self.add(2, "Wife Office Boss", "Wife Office Boss", site="9xmovies",
                 year="2026", key="wife-office-boss-2026", flag=0)
        found = fast_fetch.corroborated_adult_exposures(self.conn)
        self.assertEqual([row["post_id"] for row in found], [2])
        self.assertIn("key=wife-office-boss-2026", found[0]["evidence"])

    def test_the_cross_key_class_is_reached_without_rekeying(self):
        """The 3,482-row leak shape: one film, two slug-derived keys, one flagged copy.

        Closing it used to mean rewriting stored keys; grouping on `(clean_title, year)`
        reaches the same rows and touches no identity at all.
        """
        self.add(2, "Puli (2015) 18+ Uncut", "Puli", site="filmyzilla", year="2015",
                 key="puli-2015", flag=1)
        self.add(3, "Puli", "Puli", site="9xmovies", year="2015",
                 key="puli__2015", flag=0)
        found = {row["post_id"] for row in
                 fast_fetch.corroborated_adult_exposures(self.conn)}
        self.assertIn(3, found)

    def test_a_disputed_flag_propagates_nothing(self):
        """The regression that matters: 3,490 rows must not be hidden on this evidence."""
        self.conn.execute("DELETE FROM posts")
        self.add(10, *DISPUTED, site="ssrmovies", year="2014",
                 key="1-nenokkadine-2014", flag=1)
        self.add(11, "1 - Nenokkadine", "1 - Nenokkadine", site="moviezguru",
                 year="2014", key="1-nenokkadine_2014", flag=0)
        self.assertEqual(fast_fetch.corroborated_adult_exposures(self.conn), [])

    def test_a_corroborated_sibling_makes_the_group_usable_even_with_a_disputed_one(self):
        self.conn.execute("DELETE FROM posts")
        self.add(2, *SUGGESTION_ONLY, site="7starhd", year="2026",
                 key="wife-office-boss-2026", flag=1)
        self.add(3, *CORROBORATED, site="hdtvb", year="2026",
                 key="wife-office-boss_2026", flag=1)
        self.add(4, "Wife Office Boss", "Wife Office Boss", site="9xmovies",
                 year="2026", key="wife-office-boss-2026-hd", flag=0)
        found = {row["post_id"]: row for row in
                 fast_fetch.corroborated_adult_exposures(self.conn)}
        self.assertIn(4, found)
        self.assertEqual(found[4]["source_post_id"], 3)
        self.assertEqual(list(found), [4], "the disputed flag reached nobody")

    def test_the_unknown_key_never_groups(self):
        """`unknown` is the bucket every titleless page falls into, not one work."""
        self.conn.execute("DELETE FROM posts")
        self.add(1, *CORROBORATED, site="a", year="2026", key="unknown", flag=1)
        self.add(2, "An Entirely Different Film", "An Entirely Different Film",
                 site="b", year="1999", key="unknown", flag=0)
        self.assertEqual(fast_fetch.corroborated_adult_exposures(self.conn), [])

    def test_a_null_key_does_not_group_either(self):
        self.conn.execute("DELETE FROM posts")
        self.add(1, *CORROBORATED, site="a", year="2026", key="", flag=1)
        self.add(2, "Unrelated Title", "Unrelated Title", site="b", year="1999",
                 key="", flag=0)
        self.assertEqual(fast_fetch.corroborated_adult_exposures(self.conn), [])

    def test_a_flagged_row_is_never_its_own_exposure(self):
        self.add(2, *CORROBORATED, site="9xmovies", year="2026",
                 key="wife-office-boss-2026", flag=1)
        self.assertEqual(fast_fetch.corroborated_adult_exposures(self.conn), [])

    def test_rows_with_different_years_are_never_the_same_work(self):
        self.add(2, "Wife Office Boss", "Wife Office Boss", site="9xmovies",
                 year="2019", key="boss-2019", flag=0)
        found = {row["post_id"] for row in
                 fast_fetch.corroborated_adult_exposures(self.conn)}
        self.assertNotIn(2, found)

    def test_evidence_names_the_source_row_and_the_identity_kind(self):
        self.add(2, "Wife Office Boss", "Wife Office Boss", site="9xmovies",
                 year="2026", key="wife-office-boss-2026-hdtvb", flag=0)
        item = fast_fetch.corroborated_adult_exposures(self.conn)[0]
        self.assertIn("post 1", item["evidence"])
        #: The two keys differ, so it was the `(clean_title, year)` law that reached it.
        self.assertIn("work=('wife office boss', '2026')", item["evidence"],
                      item["evidence"])

    def test_a_row_both_laws_reach_is_claimed_once(self):
        self.add(2, "Wife Office Boss", "Wife Office Boss", site="9xmovies",
                 year="2026", key="wife-office-boss-2026", flag=0)
        found = fast_fetch.corroborated_adult_exposures(self.conn)
        self.assertEqual(len(found), 1)
        self.assertIn("key=", found[0]["evidence"], found[0]["evidence"])


class FoldTests(Fixture):
    def test_the_pass_writes_nothing_by_itself(self):
        self.add(2, "Wife Office Boss", "Wife Office Boss", site="9xmovies",
                 year="2026", key="other-key", flag=0)
        before = self.public_total()
        fast_fetch.corroborated_adult_exposures(self.conn)
        self.assertEqual(self.public_total(), before)
        self.assertEqual(self.flag_of(2), 0)

    def test_apply_hides_exactly_the_exposures_and_journals_them(self):
        self.add(2, "Wife Office Boss", "Wife Office Boss", site="9xmovies",
                 year="2026", key="other-key", flag=0)
        exposures = fast_fetch.corroborated_adult_exposures(self.conn)
        before = self.public_total()
        flipped = fast_fetch.apply_corroborated_adult_fold(self.conn, exposures)
        self.conn.commit()
        self.assertEqual(flipped, 1)
        self.assertEqual(self.public_total(), before - 1)
        rows = self.journal()
        self.assertEqual([(row["post_id"], row["source_post_id"]) for row in rows],
                         [(2, 1)])

    def test_the_fold_is_idempotent(self):
        self.add(2, "Wife Office Boss", "Wife Office Boss", site="9xmovies",
                 year="2026", key="other-key", flag=0)
        fast_fetch.apply_corroborated_adult_fold(
            self.conn, fast_fetch.corroborated_adult_exposures(self.conn))
        self.conn.commit()
        self.assertEqual(fast_fetch.corroborated_adult_exposures(self.conn), [])

    def test_a_flagged_source_is_never_flipped_again_or_journalled_twice(self):
        self.add(2, "Wife Office Boss", "Wife Office Boss", site="9xmovies",
                 year="2026", key="other-key", flag=0)
        exposures = fast_fetch.corroborated_adult_exposures(self.conn)
        exposures.append(dict(exposures[0]))
        exposures.append({"post_id": 1, "source_post_id": 1, "evidence": "itself"})
        self.assertEqual(fast_fetch.apply_corroborated_adult_fold(
            self.conn, exposures), 1)

    def test_undo_restores_this_passs_own_flips(self):
        self.add(2, "Wife Office Boss", "Wife Office Boss", site="9xmovies",
                 year="2026", key="other-key", flag=0)
        fast_fetch.apply_corroborated_adult_fold(
            self.conn, fast_fetch.corroborated_adult_exposures(self.conn))
        self.conn.commit()
        out = fast_fetch.undo_corroborated_adult_fold(self.conn)
        self.conn.commit()
        self.assertEqual(out, {"unflagged": 1, "kept": 0})
        self.assertEqual(self.flag_of(2), 0)
        self.assertEqual(self.journal(), [])

    def test_undo_keeps_a_flag_that_now_stands_on_its_own_text(self):
        self.add(2, "Wife Office Boss", "Wife Office Boss", site="9xmovies",
                 year="2026", key="other-key", flag=0)
        fast_fetch.apply_corroborated_adult_fold(
            self.conn, fast_fetch.corroborated_adult_exposures(self.conn))
        self.conn.commit()
        self.conn.execute("UPDATE posts SET title = ? WHERE id = 2", (CORROBORATED[0],))
        self.conn.commit()
        out = fast_fetch.undo_corroborated_adult_fold(self.conn)
        self.conn.commit()
        self.assertEqual(out["kept"], 1)
        self.assertEqual(self.flag_of(2), 1)

    def test_undo_keeps_a_flag_another_row_already_carried_under_the_same_key(self):
        self.add(2, "Wife Office Boss", "Wife Office Boss", site="9xmovies",
                 year="2026", key="boss-shared", flag=0)
        self.add(3, *CORROBORATED, site="hdtvb", year="2026",
                 key="boss-shared", flag=1)
        fast_fetch.apply_corroborated_adult_fold(
            self.conn, fast_fetch.corroborated_adult_exposures(self.conn))
        self.conn.commit()
        self.assertEqual(self.flag_of(2), 1)
        out = fast_fetch.undo_corroborated_adult_fold(self.conn)
        self.conn.commit()
        self.assertEqual(out, {"unflagged": 0, "kept": 1})
        self.assertEqual(self.flag_of(2), 1)

    def test_two_siblings_hidden_by_one_fold_do_not_justify_each_other(self):
        """Without the journal exclusion they would cite each other and never come back."""
        self.conn.execute("DELETE FROM posts")
        self.add(1, *CORROBORATED, site="a", year="2026", key="boss-src", flag=1)
        self.add(2, "Wife Office Boss", "Wife Office Boss", site="b", year="2026",
                 key="boss-one", flag=0)
        self.add(3, "Wife Office Boss", "Wife Office Boss", site="c", year="2026",
                 key="boss-two", flag=0)
        fast_fetch.apply_corroborated_adult_fold(
            self.conn, fast_fetch.corroborated_adult_exposures(self.conn))
        self.conn.commit()
        self.assertEqual((self.flag_of(2), self.flag_of(3)), (1, 1))
        out = fast_fetch.undo_corroborated_adult_fold(self.conn)
        self.conn.commit()
        self.assertEqual(out, {"unflagged": 2, "kept": 0})
        self.assertEqual((self.flag_of(2), self.flag_of(3)), (0, 0))

    def test_undo_on_a_database_that_was_never_folded(self):
        self.assertEqual(fast_fetch.undo_corroborated_adult_fold(self.conn),
                         {"unflagged": 0, "kept": 0})


class AuditTests(Fixture):
    def setUp(self):
        super().setUp()
        self.add(2, *DISPUTED, site="ssrmovies", year="2014",
                 key="1-nenokkadine-2014", flag=1)
        self.add(3, "A Clean Film", "A Clean Film", site="bolly4u", year="2020",
                 key="a-clean-film_2020", flag=0)

    def test_provenance_splits_reproducible_from_asserted_only(self):
        out = backfill_adult_key.audit_flags(self.conn)
        self.assertEqual(out["flagged"], 2)
        self.assertEqual(out["reproducible"], 1)
        self.assertEqual(out["asserted_only"], 1)
        self.assertEqual(out["samples"][0][0], 2)

    def test_an_unflagged_row_is_not_in_the_audit_population(self):
        self.assertEqual(backfill_adult_key.audit_flags(self.conn)["flagged"], 2)


class CliTests(Fixture):
    def run_cli(self, *argv, headroom=8000):
        buffer = io.StringIO()
        original = backfill_adult_key.mem_headroom_mb
        backfill_adult_key.mem_headroom_mb = lambda *a, **k: headroom
        try:
            with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
                code = backfill_adult_key.main([str(self.path), *argv])
        finally:
            backfill_adult_key.mem_headroom_mb = original
        return code, buffer.getvalue()

    def tearDown(self):
        super().tearDown()
        for suffix in ("-wal", "-shm", "-journal"):
            if os.path.exists(self.path + suffix):
                os.unlink(self.path + suffix)

    def test_corroborate_without_apply_writes_nothing(self):
        self.add(2, "Wife Office Boss", "Wife Office Boss", site="9xmovies",
                 year="2026", key="other-key", flag=0)
        code, out = self.run_cli("--corroborate")
        self.assertEqual(code, 0, out)
        self.assertIn("report only", out)
        self.assertEqual(self.flag_of(2), 0)
        #: The fixture's flagged row is hidden; the twin is the one public row left.
        self.assertEqual(self.public_total(), 1)

    def test_corroborate_apply_hides_and_verifies_the_arithmetic(self):
        self.add(2, "Wife Office Boss", "Wife Office Boss", site="9xmovies",
                 year="2026", key="other-key", flag=0)
        code, out = self.run_cli("--corroborate", "--apply")
        self.assertEqual(code, 0, out)
        self.assertIn("1 rows hidden", out)
        self.assertIn("corroborated exposures after the fold: 0", out)
        self.assertEqual(self.flag_of(2), 1)

    def test_undo_from_the_command_line(self):
        self.add(2, "Wife Office Boss", "Wife Office Boss", site="9xmovies",
                 year="2026", key="other-key", flag=0)
        self.run_cli("--corroborate", "--apply")
        code, out = self.run_cli("--undo")
        self.assertEqual(code, 0, out)
        self.assertIn("1 rows restored", out)
        self.assertEqual(self.flag_of(2), 0)

    def test_the_fold_refuses_when_the_box_is_out_of_memory(self):
        """The pass holds the ledger once — 150,799 rows measured 16.3 s on one CPU."""
        code, out = self.run_cli("--corroborate", headroom=1200)
        self.assertEqual(code, 3, out)
        self.assertIn("refused", out)

    def test_the_undo_is_also_memory_gated(self):
        code, out = self.run_cli("--undo", headroom=1200)
        self.assertEqual(code, 3, out)

    def test_audit_mode_reports_the_split(self):
        self.add(2, *DISPUTED, site="ssrmovies", year="2014",
                 key="1-nenokkadine-2014", flag=1)
        code, out = self.run_cli("--audit")
        self.assertEqual(code, 0, out)
        self.assertIn("asserted-only", out)
        #: Both rows here are flagged, so the public total is empty.
        self.assertEqual(self.public_total(), 0)

    def test_audit_mode_opens_the_database_read_only(self):
        self.run_cli("--audit")
        self.assertFalse(os.path.exists(self.path + "-journal"))
        self.assertFalse(os.path.exists(self.path + "-wal"))


class PlayPathTests(Fixture):
    """A link that names no post must not play, on either port."""

    def setUp(self):
        super().setUp()
        self.conn.execute("CREATE TABLE releases (id INTEGER PRIMARY KEY, post_id INTEGER)")
        self.conn.execute("CREATE TABLE download_sources (id INTEGER PRIMARY KEY,"
                          " release_id INTEGER, resource_id TEXT, source_url TEXT)")
        self.conn.execute("INSERT INTO releases VALUES (11, 1)")
        self.conn.execute("INSERT INTO download_sources VALUES (21, 11, 'r', 'https://x/a')")
        self.conn.execute("INSERT INTO download_sources VALUES (22, 999, 'r', 'https://x/b')")
        self.conn.execute("INSERT INTO download_sources VALUES (23, NULL, 'r', 'https://x/c')")
        self.conn.commit()

    def _point_release_at_a_clean_post(self):
        """Post 1 carries the fixture's flag; these two cases need an unflagged target."""
        self.add(90, "An Ordinary Film", "An Ordinary Film", site="9xmovies",
                 year="2025", key="an-ordinary-film-2025", flag=0)
        self.conn.execute("UPDATE releases SET post_id = 90 WHERE id = 11")
        self.conn.commit()

    def test_a_clean_link_answers_false(self):
        self._point_release_at_a_clean_post()
        self.assertFalse(redact.link_is_adult(21, self.path))

    def test_a_flagged_link_answers_true(self):
        self._point_release_at_a_clean_post()
        self.conn.execute("UPDATE posts SET is_18_plus = 1 WHERE id = 90")
        self.conn.commit()
        self.assertTrue(redact.link_is_adult(21, self.path))

    def test_an_unknown_link_id_is_refused(self):
        """Was `bool(row and row[0])` → False for an id that exists nowhere.

        The docstring, root `AGENTS.md` and `viewer.py:230` all claimed a typo cannot
        play; the code said the opposite.
        """
        self.assertTrue(redact.link_is_adult(999999999, self.path))

    def test_a_link_whose_post_is_gone_is_refused(self):
        """A dangling release is not a clean link: nothing lists it, so nothing plays it."""
        self.assertTrue(redact.link_is_adult(22, self.path))
        self.assertTrue(redact.link_is_adult(23, self.path))

    def test_a_database_without_the_table_still_answers_true(self):
        handle, missing = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        try:
            self.assertTrue(redact.link_is_adult(1, missing))
        finally:
            os.unlink(missing)

    def test_a_row_hidden_by_the_fold_has_its_link_refused(self):
        """The fold's whole point: hiding the listing must also close the play path."""
        self.conn.execute("INSERT INTO releases VALUES (12, 2)")
        self.conn.execute("INSERT INTO download_sources VALUES (24, 12, 'r', 'https://x/d')")
        self.add(2, "Wife Office Boss", "Wife Office Boss", site="9xmovies",
                 year="2026", key="other-key", flag=0)
        self.assertFalse(redact.link_is_adult(24, self.path))
        fast_fetch.apply_corroborated_adult_fold(
            self.conn, fast_fetch.corroborated_adult_exposures(self.conn))
        self.conn.commit()
        self.assertTrue(redact.link_is_adult(24, self.path))

    def test_the_public_list_clause_hides_the_folded_row(self):
        self.add(2, "Wife Office Boss", "Wife Office Boss", site="9xmovies",
                 year="2026", key="other-key", flag=0)
        listed = self.conn.execute(
            "SELECT id FROM posts WHERE %s ORDER BY id" % redact.adult_clause("posts")
        ).fetchall()
        self.assertEqual([row["id"] for row in listed], [2])
        fast_fetch.apply_corroborated_adult_fold(
            self.conn, fast_fetch.corroborated_adult_exposures(self.conn))
        self.conn.commit()
        listed = self.conn.execute(
            "SELECT id FROM posts WHERE %s" % redact.adult_clause("posts")).fetchall()
        self.assertEqual([row["id"] for row in listed], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
