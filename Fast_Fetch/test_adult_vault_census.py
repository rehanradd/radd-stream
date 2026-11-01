#!/usr/bin/env python3
"""test_adult_vault_census.py — the #37 census, pinned offline.

Two halves, because the task has two failure modes.

**Arithmetic half.** `adult_vault_census.PRICED` is the machine-readable copy of the tier table in
`checkpoints/20261101-08xx-...-vault-pricing-...md`. That pass priced 19 vaults and named 18 of them
in its tier rows: `rogmovies.db` was missing, and the only reason its *cost* figures stayed correct
is that its bytes had already been summed into tier C. Nothing in the tree could tell the difference,
so here is the thing that can: every published number in that table — the three tier byte totals, the
4,605,050,880 B corpus, 5-25 / 13-74 / 51-285 / 18-99 / 69-384 CPU-minutes, the 30% two-file share,
the 561 MB / 12% pair saving — is recomputed from `PRICED` here. A vault added without a tier, a size
typo, or a tier edited without the doc breaks a test instead of quietly making the plan wrong.

**Behaviour half.** Synthetic vaults in a temp dir: the collision rules (mixed key = exposure,
all-flagged key = correctly hidden, `NULL`/`''`/`unknown` never twin, `NULL` flag reads as unflagged),
the `mode=ro` guarantee at the connection level, the byte-identical-input check, the sidecar check, the
budget stop that must report *incomplete*, and the refusals that must not be mistaken for a census.

No production file, no network, no `config` import (a CI worker that cannot stat `/home/ubuntu` kills
the job at import time — measured by q5 at `eb4c0ee`). Stdlib only.

    python3 -S Fast_Fetch/test_adult_vault_census.py
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import adult_vault_census as census

#: Every figure published by the 08xx pricing pass, as data.
PUBLISHED = {
    "corpus_bytes": 4_605_050_880,
    "tier_bytes": {"A": 300_912_640, "B": 883_949_568, "C": 3_420_188_672},
    "tier_minutes": {"A": (5, 25), "B": (13, 74), "C": (51, 285)},
    "cumulative_ab_minutes": (18, 99),
    "cumulative_all_minutes": (69, 384),
    "pair_saving_bytes": 561_262_592,
    "pair_saving_percent": 12.2,
    "giants_bytes": 840_065_024 + 548_896_768,
    "giants_percent": 30.2,
    "vault_count": 19,
}


def make_vault(path: Path, rows, flag_column="is_18_plus") -> Path:
    """A throwaway vault shaped like the real ones: `posts(id, canonical_key, <flag>)`."""
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE posts (id INTEGER PRIMARY KEY, canonical_key TEXT, %s INTEGER)"
                 % flag_column)
    conn.executemany("INSERT INTO posts (id, canonical_key, %s) VALUES (?, ?, ?)" % flag_column,
                     rows)
    conn.commit()
    conn.close()
    return path


#: One mixed key (the exposure), one all-flagged key (correctly hidden), one clean key, one NULL key,
#: one empty key, one `unknown` pair, and one NULL flag. Hand-computed: rows 10, flagged 5,
#: keys_both 1, rows on that key 2, flagged on that key 1.
CENSUS_FIXTURE = [
    (1, "k-mixed", 1), (2, "k-mixed", 0),
    (3, "k-hidden", 1), (4, "k-hidden", 1),
    (5, "k-clean", 0),
    (6, None, 1),
    (7, "", 0),
    (8, "unknown", 1), (9, "unknown", 0),
    (10, "k-nullflag", None),
]


class PublishedArithmeticTests(unittest.TestCase):
    """The plan is only trustworthy while the numbers in the code are the numbers in the doc."""

    def test_every_priced_vault_sits_in_exactly_one_tier(self):
        self.assertEqual(len(census.PRICED), PUBLISHED["vault_count"],
                         "the census owes %d vaults, PRICED holds %d — a new staging vault was added "
                         "to the data dir and nobody re-priced it"
                         % (PUBLISHED["vault_count"], len(census.PRICED)))
        unknown = sorted(tier for _, tier in census.PRICED.values() if tier not in census.TIERS)
        self.assertFalse(unknown, "PRICED names tiers that do not exist: %s" % unknown)
        for tier in census.TIERS:
            self.assertTrue(census.plan(tier), "tier %s would run nothing" % tier)

    def test_tier_byte_totals_are_the_published_ones(self):
        for tier, expected in PUBLISHED["tier_bytes"].items():
            self.assertEqual(census.tier_bytes(tier), expected,
                             "tier %s is %d B, the checkpoint publishes %d B — the tier rows and the "
                             "cost table have diverged" % (tier, census.tier_bytes(tier), expected))
        self.assertEqual(sum(census.tier_bytes(t) for t in census.TIERS),
                         PUBLISHED["corpus_bytes"],
                         "the tiers do not cover the corpus exactly once")

    def test_projected_minutes_are_the_published_ones(self):
        for tier, expected in PUBLISHED["tier_minutes"].items():
            lo, hi = census.project_cost(census.tier_bytes(tier))
            self.assertEqual((round(lo / 60), round(hi / 60)), expected,
                             "tier %s projects %.0f-%.0f CPU-min, published %d-%d"
                             % (tier, lo / 60, hi / 60, *expected))

    def test_cumulative_windows_are_the_published_ones(self):
        ab = census.tier_bytes("A") + census.tier_bytes("B")
        lo, hi = census.project_cost(ab)
        self.assertEqual((round(lo / 60), round(hi / 60)), PUBLISHED["cumulative_ab_minutes"])
        whole = sum(census.tier_bytes(t) for t in census.TIERS)
        lo, hi = census.project_cost(whole)
        self.assertEqual((round(lo / 60), round(hi / 60)), PUBLISHED["cumulative_all_minutes"])

    def test_the_two_generational_giants_really_are_a_third_of_the_census(self):
        giants = census.PRICED["world4ufree.db"][0] + census.PRICED["9xmovies.db"][0]
        self.assertEqual(giants, PUBLISHED["giants_bytes"])
        self.assertAlmostEqual(100.0 * giants / PUBLISHED["corpus_bytes"],
                               PUBLISHED["giants_percent"], places=1,
                               msg="tier C no longer starts with a third of the cost, so the "
                                   "A-then-B-then-C order needs re-justifying")

    def test_generational_pairs_are_counted_once_by_default(self):
        rows = census.plan("ABC")
        counted = [r["vault"] for r in rows if r["counted"]]
        lineage = [r["vault"] for r in rows if not r["counted"]]
        self.assertEqual(sorted(lineage), sorted(census.LINEAGE),
                         "the redundant member of a pair must be reported, not summed")
        self.assertFalse(set(counted) & set(lineage))
        self.assertEqual(sorted(counted + lineage), sorted(census.PRICED))
        saved = sum(census.PRICED[name][0] for name in lineage)
        self.assertEqual(saved, PUBLISHED["pair_saving_bytes"])
        self.assertAlmostEqual(100.0 * saved / PUBLISHED["corpus_bytes"],
                               PUBLISHED["pair_saving_percent"], places=1)
        for name, current in census.LINEAGE.items():
            self.assertIn(current, counted, "%s is counted but its pair %s is not" % (current, name))

    def test_include_lineage_counts_both_members(self):
        rows = census.plan("ABC", include_lineage=True)
        self.assertTrue(all(r["counted"] for r in rows), "--include-lineage must count every member")
        self.assertEqual(len(rows), PUBLISHED["vault_count"])

    def test_the_plan_walks_tiers_in_order_and_sizes_ascending_inside_each(self):
        counted = [r for r in census.plan("ABC") if r["counted"]]
        tiers = [r["tier"] for r in counted]
        self.assertEqual(tiers, sorted(tiers), "the plan must finish tier A before it starts tier B")
        by_tier = {}
        for row in counted:
            by_tier.setdefault(row["tier"], []).append(row["bytes"])
        for tier, sizes in by_tier.items():
            self.assertEqual(sizes, sorted(sizes),
                             "tier %s should take the cheapest vault first, so a stopped run still "
                             "bought as much as it could" % tier)

    def test_plan_is_arithmetic_only(self):
        self.assertEqual(census.plan("Q"), [], "a tier nobody priced must plan nothing")
        self.assertEqual([r["vault"] for r in census.plan("A", only="kisskh.db")], ["kisskh.db"])


class CensusCountingTests(unittest.TestCase):
    """The two numbers #37 exists to produce, on rows whose truth is hand-computed."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def test_a_mixed_key_is_an_exposure_and_an_all_flagged_key_is_not(self):
        path = make_vault(self.dir / "hindilinks4u.db", CENSUS_FIXTURE)
        result = census.census_vault(path)
        self.assertEqual(result["flag_column"], "is_18_plus")
        self.assertEqual(result["rows"], 10)
        self.assertEqual(result["flagged"], 5)
        self.assertEqual(result["keys_both"], 1,
                         "only k-mixed carries both a flagged and an unflagged row")
        self.assertEqual(result["rows_on_exposed_keys"], 2)
        self.assertEqual(result["flagged_rows_on_exposed_keys"], 1)

    def test_null_empty_and_unknown_keys_never_become_twins(self):
        # keys_both stays 0 for all three: the flagged and the unflagged row share a key that
        # names no work, so the key is not an exposure.
        cases = [("hindilinks4u.db", [(1, None, 1), (2, None, 0)], 0),
                 ("filmyhit.db", [(1, "", 1), (2, "", 0)], 0),
                 ("kisskh.db", [(1, "unknown", 1), (2, "unknown", 0)], 0)]
        for name, rows, expected in cases:
            path = make_vault(self.dir / name, rows)
            self.assertEqual(census.census_vault(path)["keys_both"], expected,
                             "NULL, '' and 'unknown' are the shared bucket every titleless payload "
                             "lands in, not one work")

    def test_a_null_flag_reads_as_unflagged(self):
        path = make_vault(self.dir / "hindilinks4u.db",
                          [(1, "k", None), (2, "k", 1)])
        result = census.census_vault(path)
        self.assertEqual(result["flagged"], 1)
        self.assertEqual(result["keys_both"], 1, "COALESCE(flag,0) is how audit_adult_flags reads it")

    def test_is_adult_is_counted_when_a_vault_uses_that_name(self):
        path = make_vault(self.dir / "vegamovies.db", [(1, "k", 1), (2, "k", 0)],
                          flag_column="is_adult")
        result = census.census_vault(path)
        self.assertEqual(result["flag_column"], "is_adult")
        self.assertEqual((result["flagged"], result["keys_both"]), (1, 1))

    def test_a_database_without_a_posts_table_is_refused_not_reported_as_zero(self):
        path = self.dir / "ssrmovies.db"
        conn = sqlite3.connect(str(path))
        conn.execute("CREATE TABLE other (id INTEGER)")
        conn.commit()
        conn.close()
        with self.assertRaises(census.CensusRefused):
            census.census_vault(path)

    def test_a_posts_table_with_no_flag_column_is_refused(self):
        path = self.dir / "bolly4u.db"
        conn = sqlite3.connect(str(path))
        conn.execute("CREATE TABLE posts (id INTEGER PRIMARY KEY, canonical_key TEXT)")
        conn.commit()
        conn.close()
        with self.assertRaises(census.CensusRefused):
            census.census_vault(path)


class ReadOnlyGuaranteeTests(unittest.TestCase):
    """The freeze says no production write. That is only a rule until something enforces it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.path = make_vault(self.dir / "hindilinks4u.db", CENSUS_FIXTURE)

    def digest(self) -> str:
        return hashlib.sha256(self.path.read_bytes()).hexdigest()

    def test_the_connection_itself_refuses_an_update(self):
        conn = census.open_readonly(self.path)
        try:
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute("UPDATE posts SET is_18_plus = 0")
        finally:
            conn.close()

    def test_counting_leaves_the_vault_byte_identical(self):
        before, stat_before = self.digest(), census.fingerprint(self.path)
        census.census_vault(self.path)
        self.assertEqual(self.digest(), before, "a census that rewrites its input is not a census")
        self.assertEqual(census.fingerprint(self.path), stat_before)
        self.assertEqual(census.stray_sidecars(self.path), [])

    def test_a_vault_that_moves_under_the_run_is_refused(self):
        before = census.fingerprint(self.path)
        conn = sqlite3.connect(str(self.path))
        conn.execute("INSERT INTO posts (id, canonical_key, is_18_plus) VALUES (99, 'k9', 1)")
        conn.commit()
        conn.close()
        with self.assertRaises(census.CensusRefused) as caught:
            census.assert_untouched(self.path, before)
        self.assertIn("CHANGED", str(caught.exception))

    def test_a_sidecar_alongside_a_vault_is_refused(self):
        before = census.fingerprint(self.path)
        (self.dir / "hindilinks4u.db-wal").write_bytes(b"")
        with self.assertRaises(census.CensusRefused) as caught:
            census.assert_untouched(self.path, before)
        self.assertIn("grew", str(caught.exception),
                      "a read-only open cannot create a -wal, so one appearing means another writer")

    def test_forbidden_databases_are_never_census_targets(self):
        for name in sorted(census.FORBIDDEN):
            path = make_vault(self.dir / name, [(1, "k", 1)])
            with self.assertRaises(census.CensusRefused, msg="%s must not be censused" % name):
                census.census_vault(path)
        with self.assertRaises(census.CensusRefused):
            census.run(self.dir, "A", only="user_state.db")


class WindowBudgetTests(unittest.TestCase):
    """A window is finite. The runner must fail *loudly* rather than as a shorter success."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        for name in census.PRICED:
            if census.PRICED[name][1] == "A":
                make_vault(self.dir / name, [(1, "k", 1), (2, "k", 0)])

    def quiet(self, *args, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return census.run(self.dir, *args, **kwargs)

    def test_a_budget_that_cannot_cover_the_first_vault_reports_incomplete(self):
        result = self.quiet("A", budget=0.0)
        self.assertEqual(result["results"], [])
        self.assertFalse(result["complete"],
                         "an empty run must never read as a finished census")
        self.assertEqual({s["reason"] for s in result["skipped"]}, {"over budget"})
        self.assertEqual(len(result["skipped"]), 4)

    def test_an_ample_budget_closes_tier_a(self):
        result = self.quiet("A", budget=600.0)
        self.assertEqual(len(result["results"]), 4)
        self.assertTrue(result["complete"])
        self.assertFalse(result["skipped"])

    def test_a_vault_missing_from_disk_is_skipped_not_reported_as_zero(self):
        (self.dir / "filmyhit.db").unlink()
        result = self.quiet("A", budget=600.0)
        self.assertEqual(len(result["results"]), 3)
        self.assertFalse(result["complete"])
        self.assertIn("filmyhit.db", [s["vault"] for s in result["skipped"]])

    def test_every_count_reports_how_far_the_vault_moved_since_pricing(self):
        result = self.quiet("A", budget=600.0)
        self.assertTrue(result["complete"])
        for row in result["results"]:
            priced = census.PRICED[row["vault"]][0]
            self.assertEqual(row["size_delta_vs_pricing"],
                             (self.dir / row["vault"]).stat().st_size - priced,
                             "a census must show whether the file it counted is still the file that "
                             "was priced, because the projected cost came from that size")
            self.assertLess(row["size_delta_vs_pricing"], 0, "these fixtures are smaller than 62 MB")

    def test_an_unpriced_vault_on_disk_is_named_instead_of_ignored(self):
        make_vault(self.dir / "brandnewsite.db", [(1, "k", 1)])
        make_vault(self.dir / "hindilinks4u_readonly.db", [(1, "k", 1)])
        result = self.quiet("A", budget=600.0)
        self.assertEqual(result["unpriced_on_disk"], ["brandnewsite.db"],
                         "a snapshot copy is not a new site, but an unknown .db is")

    def test_an_empty_plan_refuses_rather_than_claiming_a_census(self):
        with self.assertRaises(census.CensusRefused):
            self.quiet("Q")
        with self.assertRaises(census.CensusRefused):
            self.quiet("A", only="never-priced.db")

    def test_refusal_mid_walk_stops_and_is_reported_as_incomplete(self):
        """A vault the census cannot count is a stop, not a row of zeroes.

        `filmyhit.db` here has a `posts` table with no flag column at all — the shape a scraper can
        leave behind — so the walk counts `hindilinks4u`, refuses, and must not carry on pretending the
        tier was measured. This used to be driven by planting a 0-byte `-wal`, which is now a *bar*
        under the 11:0x ruling rather than a refusal; `SidecarRulingTests` covers that half.
        """
        (self.dir / "filmyhit.db").unlink()          # setUp made it with a flag column; unmake it
        conn = sqlite3.connect(str(self.dir / "filmyhit.db"))
        conn.execute("CREATE TABLE posts (id INTEGER PRIMARY KEY, canonical_key TEXT)")
        conn.commit()
        conn.close()
        result = self.quiet("A", budget=600.0)
        self.assertFalse(result["complete"])
        self.assertIn("filmyhit.db", result["refused"])
        self.assertIn("no `posts.is_18_plus", result["refused"])
        self.assertEqual([r["vault"] for r in result["results"]], ["hindilinks4u.db"],
                         "the tier-A walk must stop at the first refusal, not reorder around it")


class SidecarRulingTests(unittest.TestCase):
    """The 11:0x owner ruling, as behaviour: bar the file, name it, leave the debris alone.

    Fourteen of the nineteen priced vaults sit behind a 0-byte `-wal` plus a 32,768-byte `-shm` — crash
    residue from a lane that opened them read-write and exited uncleanly. Under the 09:07 abort rule as
    written that made #37 unrunnable forever, so the ruling classifies it instead: skip and list. What
    these cases pin is the three things that make the skip honest — the barred vault is never opened
    (proved with a file that is not a database at all, so an open would raise), the debris still exists
    afterwards (this tool does not delete another lane's artifact), and the run reads as complete over
    the vaults the ruling admits while naming the bytes it did not read.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        for name in census.PRICED:
            if census.PRICED[name][1] == "A":
                make_vault(self.dir / name, [(1, "k", 1), (2, "k", 0)])

    def quiet(self, *args, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return census.run(self.dir, *args, **kwargs)

    def plant(self, name, wal_bytes=0, shm_bytes=32768, journal=False):
        base = self.dir / name
        if journal:
            base.with_name(base.name + "-journal").write_bytes(b"")
        if wal_bytes is not None:
            base.with_name(base.name + "-wal").write_bytes(b"\0" * wal_bytes)
        if shm_bytes is not None:
            base.with_name(base.name + "-shm").write_bytes(b"\0" * shm_bytes)
        return base

    def test_the_three_classes_are_distinguished_from_stat_alone(self):
        self.assertIsNone(census.sidecar_state(self.plant("kisskh.db", wal_bytes=None,
                                                         shm_bytes=None))["class"])
        self.assertEqual(census.sidecar_state(self.plant("kisskh.db"))["class"], "debris")
        self.assertEqual(census.sidecar_state(self.plant("filmyhit.db", wal_bytes=8))["class"],
                         "dirty-wal")
        self.assertEqual(census.sidecar_state(self.plant("7starhd.db", journal=True))["class"],
                         "journal")
        self.assertEqual(census.sidecar_state(self.plant("hindilinks4u.db", wal_bytes=8,
                                                         journal=True))["class"], "journal",
                         "a journal is the worst of the three, so it wins the classification")
        self.assertEqual(census.sidecar_state(self.plant("kisskh.db"))["sidecars"],
                         {"wal": 0, "shm": 32768}, "the byte sizes are the evidence; without them the "
                                                   "report says only that something was there")

    def test_a_barred_vault_is_never_opened_and_its_debris_is_never_touched(self):
        path = self.plant("hindilinks4u.db")
        path.write_bytes(b"this is not a sqlite file")     # an open would raise DatabaseError
        result = self.quiet("A", budget=600.0)
        self.assertNotIn("hindilinks4u.db", [r["vault"] for r in result["results"]])
        self.assertFalse(result.get("refused"), result.get("refused"))
        barred = [b for b in result["barred"] if b["vault"] == "hindilinks4u.db"]
        self.assertEqual(len(barred), 1)
        self.assertEqual(barred[0]["class"], "debris")
        self.assertEqual(barred[0]["sidecars"], {"wal": 0, "shm": 32768})
        self.assertEqual(path.read_bytes(), b"this is not a sqlite file",
                         "the vault stays exactly as found")
        for suffix in ("-wal", "-shm"):
            self.assertTrue((self.dir / ("hindilinks4u.db" + suffix)).exists(),
                            "%s is another lane's artifact, not this census's to delete" % suffix)

    def test_barring_the_debris_leaves_a_complete_census_of_what_the_ruling_admits(self):
        self.plant("hindilinks4u.db")
        result = self.quiet("A", budget=600.0)
        self.assertEqual(sorted(r["vault"] for r in result["results"]),
                         ["7starhd.db", "filmyhit.db", "kisskh.db"])
        self.assertTrue(result["complete"],
                        "the ruling admits three of four here, and three of four is the answer")
        self.assertEqual(result["admitted"], ["7starhd.db", "filmyhit.db", "kisskh.db"])
        self.assertEqual(result["barred_bytes"], census.PRICED["hindilinks4u.db"][0],
                         "the unread bytes have to be in the report, or 3 reads as 4")
        self.assertIn("11:0x", result["sidecar_ruling"])

    def test_a_journal_or_a_dirty_wal_bars_the_same_way_but_is_named_differently(self):
        self.plant("filmyhit.db", journal=True)
        self.plant("kisskh.db", wal_bytes=8)
        result = self.quiet("A", budget=600.0)
        self.assertEqual(sorted(b["class"] for b in result["barred"]), ["dirty-wal", "journal"],
                         "debris is crash residue; these two say a transaction did not finish, and "
                         "lumping them together would hide the difference from whoever reads it")
        self.assertEqual([r["vault"] for r in result["results"]], ["hindilinks4u.db", "7starhd.db"])

    def test_a_sidecar_growing_during_a_count_is_still_a_refusal(self):
        """The bar is for sidecars that were already there; one that appears under us is a co-writer."""
        before = census.fingerprint(self.dir / "kisskh.db")
        (self.dir / "kisskh.db-wal").write_bytes(b"")
        with self.assertRaises(census.CensusRefused) as caught:
            census.assert_untouched(self.dir / "kisskh.db", before)
        self.assertIn("grew", str(caught.exception))

    def test_the_list_command_needs_no_directory_at_all(self):
        with contextlib.redirect_stdout(io.StringIO()):
            listed = census.main(["--list", "--tier", "A",
                                  "--data-dir", "/nonexistent-q2-census-plan-dir"])
        self.assertEqual(listed, 0, "the plan is arithmetic; a window can print it before it trusts it")


def _workflow_escape(text: str) -> str:
    """`::error::` message escaping — the runner reads these three sequences and nothing else."""
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _failure_digest(result) -> str:
    """Up to three traceback lines per failing test, for the annotation a token-less lane can read.

    Same channel `test_price_projection.py` opened on 2026-11-01: `/actions/runs/{id}/logs` is 401
    without a token, `/check-runs/{id}/annotations` is 200 to anyone, and a `::error::` on the step
    process's stdout becomes one of those annotations. Three lines because `assertEqual` prints the
    value it got above the value it wanted.
    """
    heads = []
    for kind, group in (("FAIL", result.failures), ("ERROR", result.errors)):
        for test, trace in group:
            lines = [line.strip() for line in (trace or "").rstrip().splitlines() if line.strip()]
            heads.append("%s %s :: %s" % (kind, test.id(), " ⏐ ".join(lines[-3:])))
    return ("test_adult_vault_census RED — ran %d, %d failures, %d errors | sqlite %s | python %s"
            " | %s" % (result.testsRun, len(result.failures), len(result.errors),
                       sqlite3.sqlite_version, sys.version.split()[0], " || ".join(heads)))


if __name__ == "__main__":
    print("fixture: %s (offline, temp vaults only — no production file, no network)"
          % Path(__file__).name)
    _suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules["__main__"])
    _result = unittest.TextTestRunner(verbosity=2).run(_suite)
    if not _result.wasSuccessful():
        print("::error::%s" % _workflow_escape(_failure_digest(_result))[:2500])
    sys.exit(0 if _result.wasSuccessful() else 1)
