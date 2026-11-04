#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Drift guard for the Backend CI manifest (.github/workflows/backend-ci.yml).

The failure this exists to kill: AGENTS.md records that the standing push gate
"stayed green for five pushes while CI was red", and tonight's audit found
Phase-1 modules in NEITHER the 3-module gate nor the 15-step workflow. A list
nobody checks is a list that rots. So the workflow's own contents are now a
tested artifact:

  * every top-level ``Fast_Fetch/test_*.py`` must be either RUN by a step or
    listed in the machine-readable ``EXCLUDED:`` block — a new test file that
    appears in neither fails CI, which is the moment an author is forced to
    make the promote-or-exclude decision deliberately;
  * RUN and EXCLUDED must not overlap (silence both ways is rot);
  * every RUN module must exist (a module deleted from the tree must be
    deleted from the list too — a red "No such file" step is loud, but the
    guard names the drift instead of the runner guessing);
  * the crown-ordered Phase-1 modules and the two known-red debt modules
    stay in the RUN list — dropping them to "make CI green" fails here;
  * each run step invokes exactly ONE module (this runner ignores extra
    names in one call, so a merged step silently halves the gate);
  * the ``paths:`` triggers still cover ``Fast_Fetch/**`` (the filter that
    makes a docs-only push produce zero runs is load-bearing and documented).

Stdlib only; reads two files, touches no network, no DB, no subprocess.
"""

from __future__ import annotations

import glob
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WORKFLOW = os.path.join(ROOT, ".github", "workflows", "backend-ci.yml")

RUN_STEP_RE = re.compile(r"^\s*run:\s*(python3 -S .*)$")
MODULE_RE = re.compile(r"^(?:python3 -S )?Fast_Fetch/(test_\w+\.py)$")
EXCLUDED_RE = re.compile(r"^\s*#\s*EXCLUDED:\s*(test_\w+\.py)\b")

# Modules the crown ordered into CI tonight, plus the two known-red debt
# modules that must KEEP RUNNING (qoder12_cigate: "If you 'make CI green' by
# dropping or xfail-ing them, I will reject it").
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


def _manifest():
    with open(WORKFLOW, encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    run_modules, run_commands = [], []
    for line in lines:
        step = RUN_STEP_RE.match(line)
        if step:
            cmd = step.group(1).strip()
            run_commands.append(cmd)
            mods = re.findall(r"Fast_Fetch/(test_\w+\.py)", cmd)
            run_modules.extend(mods)
    excluded = [m.group(1) for line in lines if (m := EXCLUDED_RE.match(line))]
    return lines, run_modules, run_commands, excluded


class TestCiManifest(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.assertTrue(os.path.isfile(WORKFLOW), f"missing {WORKFLOW}")
        (self.lines, self.run_modules, self.run_commands,
         self.excluded) = _manifest()
        self.on_disk = sorted(os.path.basename(p) for p in
                              glob.glob(os.path.join(HERE, "test_*.py")))

    def test_every_test_module_is_accounted_for(self):
        """The drift rule: a new Fast_Fetch/test_*.py that is neither run nor
        excluded fails CI. Silence both ways is rot."""
        listed = set(self.run_modules) | set(self.excluded)
        missing = [m for m in self.on_disk if m not in listed]
        self.assertEqual(missing, [],
                         "unlisted test module(s) — promote to a CI step or add "
                         "an 'EXCLUDED:' line with a reason: " + ", ".join(missing))

    def test_no_overlap_between_run_and_excluded(self):
        both = set(self.run_modules) & set(self.excluded)
        self.assertEqual(both, set(),
                         "a module cannot be both run and excluded")

    def test_every_listed_module_exists(self):
        """Catches the other drift direction: a step or exclusion pointing at
        a file nobody shipped (yet) must be loud here, not a bare
        'No such file or directory' three workflows deep."""
        ghost = [m for m in self.run_modules if m not in self.on_disk]
        ghost += [m for m in self.excluded if m not in self.on_disk]
        self.assertEqual(ghost, [],
                         "manifest names with no file on disk: " + ", ".join(sorted(set(ghost))))

    def test_mandated_modules_are_run_not_droppable(self):
        run = set(self.run_modules)
        for module in MANDATORY_RUN:
            with self.subTest(module=module):
                self.assertIn(module, run,
                              f"{module} must stay a CI step (qoder12_cigate)")

    def test_one_module_per_invocation(self):
        """The runner ignores extra names in one call, so every run step must
        invoke exactly one suite."""
        for cmd in self.run_commands:
            with self.subTest(cmd=cmd):
                self.assertEqual(len(re.findall(r"Fast_Fetch/\S+\.py", cmd)), 1,
                                 f"multi-module step silently gates one suite: {cmd}")
                self.assertRegex(cmd, MODULE_RE,
                                 "steps must be 'python3 -S Fast_Fetch/<module>.py'")

    def test_paths_triggers_still_cover_fast_fetch(self):
        text = "\n".join(self.lines)
        self.assertIn('- "Fast_Fetch/**"', text,
                      "push/PR path filters must keep covering Fast_Fetch")

    def test_workflow_and_manifest_are_stdlib_parseable(self):
        """Cheap shape pins: run lines use `-S` (the stdlib-only law), and no
        run step pip-installs anything (comments may SAY the law; steps must
        obey it)."""
        for cmd in self.run_commands:
            self.assertIn(" -S ", cmd + " ", f"-S is project law: {cmd}")
            self.assertNotIn("pip", cmd, f"pip in a run step breaks the law: {cmd}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
