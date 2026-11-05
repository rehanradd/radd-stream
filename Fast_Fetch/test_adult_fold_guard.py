#!/usr/bin/env python3
"""The agreement gate: a key folds only when its exposed rows corroborate the flag.

Why this suite exists, in one measured number (`CROWN_ADULT_MEASUREMENT.md` §3): of the
407 exposed unflagged rows on the live catalog, 43 sit under a `canonical_key` that the
ADULT row itself contradicts — `100-bullets_2016` holds public "100 Bullets" beside
flagged "Frank Phoenix UNRATED". A literal `MAX(is_18_plus)` fold hides the legitimate
film on a mis-keyed sibling's verdict. `backfill_adult_key.classify_exposures` is the
refusal; each test below guards one direction of the error, and each named mutant in the
task #52 counterfactual reddens a named test here.

Decision pinned (tests 3 and 3b), and this is the whole of the disagreement with crown's
364/43: an identical title with a CONTRADICTING year quarantines — "Dom" 2021 beside "Dom"
2024 are two films and one series, so title equality alone is not identity. But a year
NOBODY recorded is silence, not evidence, and the full-title twin still folds: the `year`
column is empty on most of this catalog, so requiring a present year would quarantine the
very reconciliation AGENTS.md prescribes (measured: it strands 261 of the 407 exposed rows
that agree word-for-word). The bias is applied to evidence that contradicts, never to
evidence that is absent. Crown's rule reaches the first verdict for the same reason; the
suite is where both choices live rather than living implicitly inside a regex.

Offline: temp SQLite files, small `posts` tables built here, no network, no catalog.

    python3 -S Fast_Fetch/test_adult_fold_guard.py
"""
from __future__ import annotations

import contextlib
import io
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.resolve()))

import backfill_adult_key  # noqa: E402
import fast_fetch          # noqa: E402 — via report(); keep the import honest
import redact              # noqa: E402

POST_DDL = """
CREATE TABLE posts (
    id INTEGER PRIMARY KEY,
    title TEXT, clean_title TEXT, slug TEXT, url TEXT,
    source_site TEXT, year TEXT,
    canonical_key TEXT,
    is_18_plus INTEGER DEFAULT 0
)
"""


def row(ident, title, clean, year, key, flag):
    return {"id": ident, "title": title, "clean_title": clean, "year": year,
            "canonical_key": key, "is_18_plus": flag}


class Fixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "fold.db"
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute(POST_DDL)
        self.added = []

    def tearDown(self):
        self.conn.close()
        self._tmp.cleanup()

    def add(self, ident, title, clean, year, key, flag, site="ssrmovies"):
        self.conn.execute(
            "INSERT INTO posts (id, title, clean_title, slug, url, source_site,"
            " year, canonical_key, is_18_plus) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (ident, title, clean, f"slug-{ident}", f"http://x/{ident}", site,
             year, key, flag))
        self.conn.commit()
        self.added.append(ident)

    def flags(self):
        return {r["id"]: r["is_18_plus"] for r in self.conn.execute(
            "SELECT id, is_18_plus FROM posts")}

    def classify(self):
        return backfill_adult_key.classify_exposures(self.conn)

    def run_report(self, **over):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
            out = backfill_adult_key.report(self.path, **over)
        out["_printed"] = buffer.getvalue()
        return out


class GateUnitTests(Fixture):
    """`title_agrees` is the named importable gate — driven directly, not via SQL."""

    def test_true_twin_agrees(self):
        a = row(1, "Jai Bhartiya", "Jai Bhartiya", "2022", "k", 0)
        b = row(2, "Jai Bhartiya UNRATED", "Jai Bhartiya", "2022", "k", 1)
        self.assertTrue(backfill_adult_key.title_agrees(a, b))

    def test_collision_disagrees(self):
        a = row(1, "100 Bullets", "100 Bullets", "2016", "100-bullets_2016", 0)
        b = row(2, "Frank Phoenix UNRATED", "Frank Phoenix", "2016",
                "100-bullets_2016", 1)
        ok, reason = backfill_adult_key.titles_agree_with_reason(a, b)
        self.assertFalse(ok)
        self.assertEqual(reason, "title_disagree")

    def test_year_drift_pin(self):
        """DECISION PINNED: identical title, CONTRADICTING years → quarantine, not fold."""
        a = row(1, "Black Mirror", "Black Mirror", "2019", "black-mirror", 0)
        b = row(2, "Black Mirror", "Black Mirror", "2025", "black-mirror", 1)
        ok, reason = backfill_adult_key.titles_agree_with_reason(a, b)
        self.assertFalse(ok)
        self.assertEqual(reason, "year_drift")

    def test_absent_year_is_silence_not_contradiction(self):
        """DECISION PINNED: identical title, no year on either side → the twin folds.

        This is the divergence from crown's 364/43, made explicit: 269 of the 407 exposed
        rows carry no `year` column at all and 261 of them corroborate their sibling
        word-for-word, so treating a missing year as grounds to refuse would strand
        essentially the whole fold. Absence is not evidence.
        """
        a = row(1, "Alpha Movie", "Alpha Movie", "", "alpha-movie", 0)
        b = row(2, "Alpha Movie UNRATED", "Alpha Movie", None, "alpha-movie", 1)
        self.assertTrue(backfill_adult_key.title_agrees(a, b))
        self.assertEqual(backfill_adult_key.titles_agree_with_reason(a, b),
                         (True, "agree"))

    def test_year_may_be_derived_from_the_title_text(self):
        """No `year` column, but the row's own title says 2019 against 2025 → drift."""
        a = row(1, "Black Mirror (2019)", "Black Mirror (2019)", "", "black-mirror", 0)
        b = row(2, "Black Mirror (2025)", "Black Mirror (2025)", "", "black-mirror", 1)
        ok, reason = backfill_adult_key.titles_agree_with_reason(a, b)
        self.assertFalse(ok)
        self.assertEqual(reason, "year_drift")

    def test_boilerplate_still_agrees(self):
        a = row(1, "Darbar", "Darbar", "2020", "darbar_2020", 0)
        b = row(2, "Darbar (2020) Dual Audio Hindi ORG 720p", "Darbar", "2020",
                "darbar_2020", 1)
        self.assertTrue(backfill_adult_key.title_agrees(a, b))

    def test_typo_tolerance_one_edit(self):
        a = row(1, "SChor Bazaar", "SChor Bazaar", "2023", "chor-bazaar_2023", 0)
        b = row(2, "Chor Bazaar", "Chor Bazaar", "2023", "chor-bazaar_2023", 1)
        self.assertTrue(backfill_adult_key.title_agrees(a, b))

    def test_compact_tokenisation(self):
        a = row(1, "Rangi Taranga", "Rangi Taranga", "2015", "rangitaranga_2015", 0)
        b = row(1, "RangiTaranga", "RangiTaranga", "2015", "rangitaranga_2015", 1)
        self.assertTrue(backfill_adult_key.title_agrees(a, b))

    def test_subset_is_not_agreement(self):
        a = row(1, "Death Race", "Death Race", "2000", "death-race_2000", 0)
        b = row(2, "Death Race 2000", "Death Race 2000", "1975",
                "death-race_2000", 1)
        ok, reason = backfill_adult_key.titles_agree_with_reason(a, b)
        self.assertFalse(ok)
        self.assertEqual(reason, "title_disagree")


class ClassifyTests(Fixture):
    def test_agree_and_quarantine_split(self):
        self.add(1, "Alpha", "Alpha", "2001", "alpha_2001", 0)
        self.add(2, "Alpha", "Alpha", "2001", "alpha_2001", 1)
        self.add(3, "100 Bullets", "100 Bullets", "2016", "100-bullets_2016", 0)
        self.add(4, "Frank Phoenix UNRATED", "Frank Phoenix", "2016",
                 "100-bullets_2016", 1)
        out = self.classify()
        self.assertEqual(out["exposed_rows"], 2)
        self.assertEqual(out["agree_rows"], 1)
        self.assertEqual(out["quarantine_rows"], 1)
        self.assertIn("alpha_2001", out["agree_keys"])
        self.assertIn("100-bullets_2016", out["quarantine_keys"])
        self.assertEqual([t[0] for t in out["fold_targets"]], [1])

    def test_half_agree_key_is_refused_whole(self):
        """The fold is per-key: one quarantined exposed row refuses the whole key,
        and the split line counts rows by what will actually happen to them."""
        self.add(1, "Beta", "Beta", "2002", "beta_2002", 0)      # agrees on its own…
        self.add(2, None, None, "2002", "beta_2002", 0)          # …but this one can't
        self.add(3, "Beta UNRATED", "Beta", "2002", "beta_2002", 1)
        out = self.classify()
        self.assertEqual(out["agree_rows"], 0)    # nothing folds: key refused
        self.assertEqual(out["quarantine_rows"], 2)
        self.assertIn("beta_2002", out["quarantine_keys"])
        self.assertEqual(out["fold_targets"], [])
        per_row = {rid: (ok, reason) for rid, ok, reason, _s in
                   out["verdicts"]["beta_2002"]}
        self.assertEqual(per_row[1], (True, "agree"))       # row verdict preserved…
        self.assertEqual(per_row[2], (False, "no_title"))   # …key verdict overrides

    def test_no_title_row_quarantined_not_folded(self):
        self.add(1, None, None, "2003", "ghost_2003", 0)
        self.add(2, "Ghost", "Ghost", "2003", "ghost_2003", 1)
        out = self.classify()
        reasons = [r for (_id, ok, r, _s) in out["verdicts"]["ghost_2003"]]
        self.assertIn("no_title", reasons)
        self.assertEqual(out["fold_targets"], [])

    def test_null_clean_title_falls_back_to_title(self):
        self.add(1, "Gamma Film", None, "2004", "gamma_2004", 0)
        self.add(2, "Gamma Film UNRATED", "Gamma Film", "2004", "gamma_2004", 1)
        out = self.classify()
        self.assertEqual(out["agree_rows"], 1)
        self.assertEqual(len(out["fold_targets"]), 1)

    def test_no_key_rows_never_folded(self):
        for key, ident in ((None, 10), ("", 11), ("unknown", 12)):
            self.add(ident, "Delta", "Delta", "2005", key, 0)
        self.add(900, "Delta UNRATED", "Delta", "2005", "delta_2005", 1)
        self.add(901, "Delta", "Delta", "2005", "delta_2005", 0)
        out = self.classify()
        self.assertEqual(out["exposed_keys"], 1)
        self.assertEqual([t[0] for t in out["fold_targets"]], [901])


class ApplyUndoTests(Fixture):
    def test_apply_folds_agree_exactly_and_moves_the_total(self):
        self.add(1, "Alpha", "Alpha", "2001", "alpha_2001", 0)
        self.add(2, "Alpha", "Alpha", "2001", "alpha_2001", 1)
        self.add(3, "100 Bullets", "100 Bullets", "2016", "100-bullets_2016", 0)
        self.add(4, "Frank Phoenix UNRATED", "Frank Phoenix", "2016",
                 "100-bullets_2016", 1)
        before = backfill_adult_key.public_total(self.conn)
        out = self.run_report(apply=True)
        self.assertEqual(out["flipped"], 1)
        self.assertTrue(out["verified"])
        self.assertEqual(out["public_total_after"], before - 1)
        flags = self.flags()
        self.assertEqual(flags[1], 1)     # agreed row folded
        self.assertEqual(flags[3], 0)     # collided row untouched — still public
        self.assertEqual(flags[4], 1)     # the original flag stands
        self.assertIn("exposed rows 2 = agree 1 + quarantine 1", out["_printed"])

    def test_apply_all_is_the_ungated_legacy_path(self):
        self.add(1, "Alpha", "Alpha", "2001", "alpha_2001", 0)
        self.add(2, "Alpha", "Alpha", "2001", "alpha_2001", 1)
        self.add(3, "100 Bullets", "100 Bullets", "2016", "100-bullets_2016", 0)
        self.add(4, "Frank Phoenix UNRATED", "Frank Phoenix", "2016",
                 "100-bullets_2016", 1)
        out = self.run_report(apply_all=True)
        self.assertEqual(out["flipped"], 2)      # the collision folded too
        self.assertIn("UN-GATED legacy fold", out["_printed"])

    def test_undo_restores_byte_exactly_including_null(self):
        self.add(1, "Alpha", "Alpha", "2001", "alpha_2001", 0)
        self.conn.execute("UPDATE posts SET is_18_plus = NULL WHERE id = 1")
        self.add(2, "Alpha", "Alpha", "2001", "alpha_2001", 1)
        self.conn.commit()
        pre = dict(self.conn.execute("SELECT id, is_18_plus FROM posts ORDER BY id"))
        self.assertEqual(pre[1], None)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
            code_a = backfill_adult_key.main([str(self.path), "--apply"])
            code_u = backfill_adult_key.main([str(self.path), "--undo"])
        self.assertEqual((code_a, code_u), (0, 0))
        post = dict(self.conn.execute("SELECT id, is_18_plus FROM posts ORDER BY id"))
        self.assertEqual(post, pre)   # byte-exact, NULL included
        left = self.conn.execute(
            "SELECT COUNT(*) FROM adult_key_fold_journal").fetchone()[0]
        self.assertEqual(left, 0)

    def test_public_total_verification_gates_a_mismatched_fold(self):
        """If flipped rows and the public-total delta ever disagree, the write is
        rolled back. Remove the verification and this test goes RED."""
        self.add(1, "Alpha", "Alpha", "2001", "alpha_2001", 0)
        self.add(2, "Alpha", "Alpha", "2001", "alpha_2001", 1)
        original = backfill_adult_key.fold_rows
        broken = lambda conn, targets: (conn.execute(
            "UPDATE posts SET is_18_plus = 1 WHERE id = 1"), 5)[1]  # does 1, says 5
        backfill_adult_key.fold_rows = broken
        try:
            out = self.run_report(apply=True)
        finally:
            backfill_adult_key.fold_rows = original
        self.assertFalse(out["verified"])
        self.assertEqual(out["public_total_after"], out["public_total_before"])
        self.assertEqual(self.flags()[1], 0)     # rolled back — nothing half-written


class ProjectionIndependenceTests(Fixture):
    def setUp(self):
        super().setUp()
        self.conn.execute("CREATE TABLE cat_works (id INTEGER PRIMARY KEY,"
                          " work_key TEXT UNIQUE, is_18_plus INTEGER DEFAULT 0)")
        self.conn.execute("CREATE TABLE cat_work_sites (work_id INTEGER, post_id INTEGER)")
        self.conn.execute("CREATE TABLE cat_projection_meta (key TEXT, value TEXT)")
        self.conn.commit()

    def test_projection_rolls_up_a_gated_key_unchanged(self):
        # the collision shape: gate must refuse the fold...
        self.add(1, "100 Bullets", "100 Bullets", "2016", "100-bullets_2016", 0)
        self.add(2, "Frank Phoenix UNRATED", "Frank Phoenix", "2016",
                 "100-bullets_2016", 1)
        out = self.run_report(apply=True)
        self.assertEqual(out["flipped"], 0)
        # ...but the projection still inherits the flag the LEDGER already carries:
        # its rule is any() over posts folded into the work, and it cannot invent a
        # collision — so it runs independent of the gate, exactly as documented.
        self.conn.execute("INSERT INTO cat_works (id, work_key, is_18_plus)"
                          " VALUES (7, '100-bullets_2016', 0)")
        self.conn.execute("INSERT INTO cat_work_sites VALUES (7, 1)")
        self.conn.execute("INSERT INTO cat_work_sites VALUES (7, 2)")
        self.conn.commit()
        hidden, dropped = backfill_adult_key.apply_projection(self.conn)
        self.assertEqual(hidden, 1)
        self.assertEqual(self.conn.execute(
            "SELECT is_18_plus FROM cat_works WHERE id = 7").fetchone()[0], 1)


class EmptyTokenRefusalTests(Fixture):
    """A title made entirely of distribution vocabulary corroborates NOTHING — and the
    gate must say so, in both directions, because growing `BOILERPLATE_TOKENS` is how a
    live work gets silently blinded.

    This is order #71's defect turned into a test. `CROWN_VERIFY_70` §4 measured that the
    23-word vocabulary filed with order #70 empties the token set of five distinct
    `clean_title` values in the production catalog, one of which is a real film: `AKA`
    (2023, Netflix Original — rows 10892 hdtvb, 13609 moviezguru, 145867 filmiyin).
    `titles_corroborate` bails on an empty set, so the effect is a permanent MISSED hide,
    never a mis-hide — the safe direction, and the reason `aka` came out of the patch
    rather than the fixtures being edited. Three titles still empty under the 22-word
    version and they are pinned here so a future word cannot empty a fourth quietly.

    Offline: temp SQLite files, no network, no catalog read.
    """

    # Re-measured on merged_catalog_20261025.db (108,907 distinct non-empty clean_title
    # values) against THIS module's vocabulary: exactly these three empty out.
    BOILERPLATE_ONLY = ["(2023) Unofficial", "(2024) HQ", "(2024) Unofficial"]

    def test_boilerplate_only_titles_tokenise_to_nothing(self):
        for text in self.BOILERPLATE_ONLY:
            with self.subTest(title=text):
                self.assertEqual(backfill_adult_key.title_tokens(text), frozenset())

    def test_corroborate_refuses_an_empty_set_even_against_itself(self):
        """The direction that matters: empty vs empty is NOT "the same title"."""
        self.assertFalse(backfill_adult_key.titles_corroborate(frozenset(), frozenset()))
        self.assertFalse(
            backfill_adult_key.titles_corroborate(frozenset(), frozenset(["kaduva"])))

    def test_empty_against_empty_is_refused_not_folded(self):
        a = row(1, "(2024) HQ", "(2024) HQ", "2024", "hq_2024", 0)
        b = row(2, "(2023) Unofficial", "(2023) Unofficial", "2023", "hq_2024", 1)
        ok, reason = backfill_adult_key.titles_agree_with_reason(a, b)
        self.assertFalse(ok)
        self.assertEqual(reason, "no_title")

    def test_empty_against_a_named_work_is_refused(self):
        a = row(1, "Kaduva", "Kaduva", "2022", "kaduva_2022", 0)
        b = row(2, "(2024) HQ", "(2024) HQ", "2024", "kaduva_2022", 1)
        ok, reason = backfill_adult_key.titles_agree_with_reason(a, b)
        self.assertFalse(ok)
        self.assertEqual(reason, "no_title")

    def test_a_key_whose_rows_are_all_boilerplate_never_folds(self):
        self.add(1, "(2024) HQ", "(2024) HQ", "2024", "boilerplate_only_key", 0)
        self.add(2, "(2023) Unofficial", "(2023) Unofficial", "2023",
                 "boilerplate_only_key", 1)
        out = self.classify()
        self.assertEqual(out["agree_rows"], 0)
        self.assertEqual(out["quarantine_rows"], 1)
        exposed_id, agreed, why, source = out["verdicts"]["boilerplate_only_key"][0]
        self.assertEqual(exposed_id, 1)
        self.assertFalse(agreed)
        self.assertEqual(why, "no_title")
        self.assertIsNone(source)
        self.assertEqual(self.flags()[1], 0)      # refused outright: nothing written

    def test_aka_stays_a_title_and_its_twin_still_folds(self):
        """The regression this patch is named for: `aka` is NOT distribution vocabulary."""
        self.assertNotIn("aka", backfill_adult_key.BOILERPLATE_TOKENS)
        self.assertEqual(backfill_adult_key.title_tokens("AKA"), frozenset(["aka"]))
        self.add(1, "AKA", "AKA", "2023", "aka_2023", 0)
        self.add(2, "AKA Hindi Dubbed", "AKA", "2023", "aka_2023", 1)
        out = self.classify()
        self.assertEqual(out["agree_rows"], 1)
        self.assertEqual(out["quarantine_rows"], 0)

    def test_a_growth_of_the_vocabulary_folds_the_work_it_is_for(self):
        """`malayalam` is a tag one site adds; the 2022 film under both spellings folds."""
        self.assertEqual(
            backfill_adult_key.title_tokens("Kaduva Malayalam"),
            backfill_adult_key.title_tokens("Kaduva"))
        self.add(1, "Kaduva (2022) Malayalam Full Movie", "Kaduva Malayalam", "2022",
                 "kaduva_2022", 0)
        self.add(2, "Kaduva 2022 Dual Audio Hindi (Cleaned)", "Kaduva", "2022",
                 "kaduva_2022", 1)
        out = self.classify()
        self.assertEqual(out["agree_rows"], 1)
        self.assertEqual(out["quarantine_rows"], 0)


class SplitLineTests(Fixture):
    def test_report_mode_prints_the_agree_quarantine_split(self):
        self.add(1, "Alpha", "Alpha", "2001", "alpha_2001", 0)
        self.add(2, "Alpha", "Alpha", "2001", "alpha_2001", 1)
        out = self.run_report()
        self.assertIn("gate: exposed rows 1 = agree 1 + quarantine 0", out["_printed"])
        self.assertIn("report only; pass --apply for the agree-gated fold",
                      out["_printed"])
        # report mode performed no write at all:
        self.assertEqual(self.flags()[1], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
