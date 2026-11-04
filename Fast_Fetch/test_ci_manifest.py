#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Drift guard for the Backend CI manifest (.github/workflows/backend-ci.yml).

The failure this exists to kill, in the order it was measured:

  1. AGENTS.md records a push gate that "stayed green for five pushes while CI
     was red"; the 2026-11-05 audit then found Phase-1 modules in NEITHER the
     3-module gate nor the workflow. A list nobody checks is a list that rots:
       * every top-level ``Fast_Fetch/test_*.py`` must be either RUN by a step
         or listed in the machine-readable ``EXCLUDED:`` block;
       * RUN and EXCLUDED must not overlap;
       * each run step invokes exactly ONE module (the runner ignores extra
         names in one call, so a merged step silently halves the gate);
       * the crown-ordered modules stay in RUN — dropping them to "make CI
         green" fails here;
       * the ``paths:`` triggers still cover ``Fast_Fetch/**``.
  2. Order qoder12_ci_retarget added three more, each aimed at a hole that
     was actually shipped this time:
       * an UNTRACKED file named by a run step passed the disk-glob guard while
         a clean CI checkout failed with exit 2 — so every run-step module must
         now be tracked in the commit CI checks out (git unavailable is a
         LOUD failure, never a silent skip);
       * a fork branch legitimately lacks trunk's suites — a module not on
         disk must at least exist in ``origin/master``'s tree, or it is a
         typo'd ghost; if that read is unavailable the test FAILS, loudly;
       * the lane's stale-fork workflow (15+6 steps) was a proper SUBSET of
         trunk's 38-step file, and had it won a merge, trunk would have lost
         ~20 suites including adult guards — so the manifest must never be a
         subset of ``git show origin/master:.github/workflows/backend-ci.yml``.

Stdlib only. Reads files and runs read-only git queries; no network, no DB.
"""

from __future__ import annotations

import glob
import os
import re
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WORKFLOW = os.path.join(ROOT, ".github", "workflows", "backend-ci.yml")
TRUNK_REF = os.environ.get("RADD_CI_MANIFEST_TRUNK", "origin/master")
TRUNK_WORKFLOW = ".github/workflows/backend-ci.yml"
# The commit whose tree defines "tracked". Default HEAD = exactly what a clean
# CI checkout of the pushed commit gets; RADD_CI_MANIFEST_REF lets the branch
# owner prove a candidate commit before moving the ref.
MANIFEST_REF = os.environ.get("RADD_CI_MANIFEST_REF", "HEAD")

RUN_STEP_RE = re.compile(r"^\s*run:\s*((?:time\s+)?python3 -S .*)$")
MODULE_PATH_RE = re.compile(r"(Fast_Fetch/(?:importers/)?test_\w+\.py)")
MODULE_RE = re.compile(r"^(?:time )?python3 -S Fast_Fetch/(?:importers/)?test_\w+\.py$")
EXCLUDED_RE = re.compile(r"^\s*#\s*EXCLUDED:\s*(test_\w+\.py)\b")

# Modules the crown ordered into CI (qoder12_cigate), including the two that
# are red at this fork's base but green on trunk and must KEEP RUNNING
# (qoder12_ci_retarget: the fix is taking trunk's dependency, not dropping
# the step).
MANDATORY_RUN = (
    "test_resolved_cache.py",
    "test_host_classifier.py",
    "test_catalog_exporter.py",
    "test_domain_resolver.py",
    "test_fast_fetch_domains.py",
    "test_ci_manifest.py",
    "test_evidence_writeback.py",
    "test_merge_catalogs.py",
)


def _git(*args):
    """Read-only git query. Returns CompletedProcess, or None if git itself
    is not runnable — callers must then fail, never pass silently."""
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                              text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None


def _parse_workflow(text):
    """(run_paths, run_commands, excluded_stems) from workflow file text."""
    run_paths, run_commands = [], []
    for line in text.splitlines():
        step = RUN_STEP_RE.match(line)
        if step:
            cmd = step.group(1).strip()
            run_commands.append(cmd)
            run_paths.extend(MODULE_PATH_RE.findall(cmd))
    excluded = [m.group(1) for line in text.splitlines()
                if (m := EXCLUDED_RE.match(line))]
    return run_paths, run_commands, excluded


class TestCiManifest(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.assertTrue(os.path.isfile(WORKFLOW), f"missing {WORKFLOW}")
        with open(WORKFLOW, encoding="utf-8") as fh:
            self.text = fh.read()
        (self.run_paths, self.run_commands,
         self.excluded) = _parse_workflow(self.text)
        self.top_level = sorted(os.path.basename(p) for p in
                                glob.glob(os.path.join(HERE, "test_*.py")))

    # ---------- coverage of the disk ----------

    def test_every_test_module_is_accounted_for(self):
        """A new Fast_Fetch/test_*.py that is neither run nor excluded fails
        CI — the moment the promote-or-exclude decision is made deliberately."""
        listed = {os.path.basename(p) for p in self.run_paths} | set(self.excluded)
        missing = [m for m in self.top_level if m not in listed]
        self.assertEqual(missing, [],
                         "unlisted test module(s) — promote to a CI step or add "
                         "an 'EXCLUDED:' line with a reason: " + ", ".join(missing))

    def test_no_overlap_between_run_and_excluded(self):
        both = {os.path.basename(p) for p in self.run_paths} & set(self.excluded)
        self.assertEqual(both, set(), "a module cannot be both run and excluded")

    def test_mandated_modules_are_run_not_droppable(self):
        run = {os.path.basename(p) for p in self.run_paths}
        for module in MANDATORY_RUN:
            with self.subTest(module=module):
                self.assertIn(module, run,
                              f"{module} must stay a CI step (qoder12_cigate/"
                              f"qoder12_ci_retarget: dropping or xfail-ing is rejected)")

    def test_one_module_per_invocation(self):
        for cmd in self.run_commands:
            with self.subTest(cmd=cmd):
                self.assertEqual(len(MODULE_PATH_RE.findall(cmd)), 1,
                                 f"multi-module step silently gates one suite: {cmd}")
                self.assertRegex(cmd, MODULE_RE,
                                 "steps must be 'python3 -S Fast_Fetch/<module>.py'")

    def test_paths_triggers_still_cover_fast_fetch(self):
        self.assertIn('- "Fast_Fetch/**"', self.text,
                      "push/PR path filters must keep covering Fast_Fetch")

    def test_workflow_steps_are_stdlib_only(self):
        """`-S` is project law in every run step, and no step pip-installs.
        Scoped to the commands: the file's PROSE states the law and must not
        trip this (it bit its own author once)."""
        for cmd in self.run_commands:
            self.assertIn(" -S ", cmd + " ", f"-S is project law: {cmd}")
            self.assertNotIn("pip", cmd, f"pip in a run step breaks the law: {cmd}")

    # ---------- tracked-ness (order qoder12_ci_retarget, Task 2.2) ----------

    def _tree_files(self, ref, why):
        """Set of paths in a git tree; FAILS loudly (never passes) if git
        cannot answer — a guard that silently skips is the bug we are fixing."""
        proc = _git("ls-tree", "-r", "--name-only", ref)
        if proc is None:
            self.fail(f"git is unavailable ({why}) — failing loudly by order "
                      "qoder12_ci_retarget, a skipped check is not a passed one")
        if proc.returncode != 0:
            self.fail(f"git ls-tree {ref} failed ({proc.stderr.strip()}, {why})")
        return set(proc.stdout.splitlines())

    def test_every_excluded_name_exists_somewhere(self):
        """The other drift direction: an EXCLUDED: line pointing at a file
        that exists on neither disk nor trunk is a fossil of a deleted test
        (or a typo) and must not linger in the manifest."""
        disk = set(self.top_level)
        trunk_names = {os.path.basename(p)
                       for p in self._tree_files(TRUNK_REF, "excluded-ghost check")}
        ghost = sorted(m for m in set(self.excluded)
                       if m not in disk and m not in trunk_names)
        self.assertEqual(ghost, [],
                         "EXCLUDED lines naming a file on neither disk nor "
                         + TRUNK_REF + ": " + ", ".join(ghost))

    def test_every_run_module_is_tracked_and_resolvable(self):
        """Every module named by a run: step must be resolvable in BOTH worlds:
          * on disk here -> tracked in {MANIFEST_REF} (the commit CI checks
            out). An untracked-but-present file is EXACTLY the bug this guard
            could not see before: the disk glob passed locally while a clean
            checkout failed with exit 2.
          * not on disk (legitimately newer on trunk than on this fork) -> it
            must exist in TRUNK_REF's tree, or the name is a typo'd ghost.
        If git cannot answer, this FAILS with a stated reason: a guard that
        silently skips is the failure mode being fixed, not the fix."""
        tracked = self._tree_files(MANIFEST_REF, "tracked-module check")
        trunk_files = self._tree_files(TRUNK_REF, "ghost check fallback")
        problems = []
        for path in sorted(set(self.run_paths)):
            if os.path.isfile(os.path.join(ROOT, path)):
                if path not in tracked:
                    problems.append(
                        f"{path}: present on disk but NOT tracked in "
                        f"{MANIFEST_REF} — its owner must git add + commit it "
                        "before this step can exist")
            elif path not in trunk_files:
                problems.append(f"{path}: named by a run: step but exists on "
                                f"neither disk nor {TRUNK_REF} — typo'd ghost")
        self.assertEqual(problems, [], "\n".join(problems))

    # ---------- coverage-regression vs trunk (Task 2.3) ----------

    def test_manifest_is_never_a_subset_of_trunks(self):
        """The fork disaster this pins: our stale workflow file was 15+6 steps
        against trunk's 38, and had it won a merge, ~20 trunk suites — among
        them the adult/redaction guards — would have silently vanished.
        The manifest must refuse to bless a run set that drops any trunk
        suite. If the trunk read is unavailable this FAILS, never passes."""
        show = _git("show", f"{TRUNK_REF}:{TRUNK_WORKFLOW}")
        if show is None:
            self.fail("git is unavailable — cannot read the trunk manifest to "
                      "prove we run everything trunk runs; failing by order")
        if show.returncode != 0:
            self.fail(f"git show {TRUNK_REF}:{TRUNK_WORKFLOW} failed "
                      f"({show.stderr.strip()}) — the coverage-regression guard "
                      "refuses to pass while blind")
        trunk_paths, _, _ = _parse_workflow(show.stdout)
        missing = sorted(set(trunk_paths) - set(self.run_paths))
        self.assertEqual(missing, [],
                         "this workflow is LOSING trunk suites — every module "
                         f"{TRUNK_REF} runs must stay a step here: "
                         + ", ".join(missing))


if __name__ == "__main__":
    unittest.main(verbosity=2)
