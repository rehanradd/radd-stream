#!/usr/bin/env python3
"""Offline guard: the CI inventory and the test tree must agree in both directions.

Measured 2026-10-30 on trunk `6a441ec`: 83 `test_*.py` modules existed under
`Fast_Fetch/` and `Fast_Fetch/importers/`, and `.github/workflows/backend-ci.yml`
ran 32 of them. Nothing noticed the other 51. Twenty-one of those were real
unittest suites with a `unittest.main`; three of them (`test_host_resolvers.py`,
`test_stream_resolvers.py`, `test_convert_mp4moviez.py`) were offline and were
not covered by the workflow's own written exclusion for per-site parser tests.
They were simply never wired up, and no test could have said so.

This suite closes the inventory rather than one instance of it:

  * every `test_*.py` under `Fast_Fetch/` and `Fast_Fetch/importers/` is either a
    `name: 🧪` step in the workflow or an entry in EXCLUDED with a stated reason;
  * every step names a file that still exists (a renamed module leaves a red X
    instead of a silent zero-test green);
  * an EXCLUDED entry that no longer exists is itself a failure, so the list
    cannot rot into a set of permissions for files that are gone;
  * the step list has no duplicates.

Offline: reads the workflow and two directory listings. No network, no catalog.
"""
from __future__ import annotations

import pathlib
import re
import unittest

BASE_DIR = pathlib.Path(__file__).resolve().parent          # Fast_Fetch/
REPO_ROOT = BASE_DIR.parent                                 # repo root
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "backend-ci.yml"

#: Every suite the workflow deliberately does not run, with the reason it does not.
#: The workflow header states the policy; this table is where it is enforceable.
EXCLUDED = {
    "test_5movierulz_import.py": "per-site importer suite (see workflow header)",
    "test_animahd_import.py": "per-site importer suite (see workflow header)",
    "test_aryplus_import.py": "per-site importer suite (see workflow header)",
    "test_desiserials_import.py": "per-site importer suite (see workflow header)",
    "test_dramacool_import.py": "per-site importer suite (see workflow header)",
    "test_filmiyin_import.py": "per-site importer suite (see workflow header)",
    "test_filmyhit_import.py": "per-site importer suite (see workflow header)",
    "test_filmywap_import.py": "per-site importer suite (see workflow header)",
    "test_import_humtv.py": "per-site importer suite (see workflow header)",
    "test_import_wp_family.py": "per-site importer suite (see workflow header)",
    "test_kisskh_import.py": "per-site importer suite (see workflow header)",
    "test_kuttymovies_import.py": "per-site importer suite (see workflow header)",
    "test_levidia_import.py": "per-site importer suite (see workflow header)",
    "test_moviecok_import.py": "per-site importer suite (see workflow header)",
    "test_moviesmela_import.py": "per-site importer suite (see workflow header)",
    "test_mp4moviez_import.py": "per-site importer suite (see workflow header)",
    "test_pagalmovies_import.py": "per-site importer suite (see workflow header)",
    "test_themoviebox_import.py": "per-site importer suite (see workflow header)",
}

#: `- name: 🧪 test_foo.py` and `- name: 🧪 test_admin_panel.py (timed)`.
STEP = re.compile(r"^\s*-\s*name:\s*🧪\s+(\S+\.py)")
#: The command a step runs. A step that names a file but runs something else is a lie.
RUN = re.compile(r"^\s*run:\s+(?:time\s+)?python3\s+-S\s+(\S+\.py)")


def test_modules() -> dict[str, pathlib.Path]:
    """Every real test module, basename -> path. Duplicate basenames are a failure."""
    found = {}
    for path in sorted(BASE_DIR.glob("test_*.py")) + sorted(BASE_DIR.glob("importers/test_*.py")):
        if path.name in found:
            raise AssertionError("two test modules share a basename: %s and %s"
                                 % (found[path.name], path))
        found[path.name] = path
    return found


def workflow_lines():
    return WORKFLOW.read_text(encoding="utf-8").splitlines()


def steps():
    """(name, run_target_or_None) for every 🧪 step, in file order."""
    out, pending = [], None
    for line in workflow_lines():
        match = STEP.match(line)
        if match:
            pending = match.group(1)
            out.append([pending, None])
            continue
        if pending is not None:
            run = RUN.match(line)
            if run:
                out[-1][1] = run.group(1)
                pending = None
    return [(name, target) for name, target in out]


class StepTargetTests(unittest.TestCase):
    def test_every_step_names_a_file_that_exists(self):
        missing = []
        for name, target in steps():
            if target is None:
                missing.append("%s: step has no `python3 -S <file>` line" % name)
                continue
            path = (REPO_ROOT / target) if "/" in target else (BASE_DIR / target)
            if not path.is_file():
                missing.append("%s: names %s, which does not exist" % (name, target))
        self.assertFalse(missing, "CI names a file that is gone:\n" + "\n".join(missing))

    def test_a_step_runs_the_file_it_names(self):
        wrong = []
        for name, target in steps():
            if target is not None and not target.endswith(name):
                wrong.append("%s runs %s" % (name, target))
        self.assertFalse(wrong, "step name and command disagree:\n" + "\n".join(wrong))

    def test_no_suite_runs_twice(self):
        names = [name for name, _t in steps()]
        duplicates = sorted({n for n in names if names.count(n) > 1})
        self.assertFalse(duplicates, "suite added twice: %s" % duplicates)

    def test_the_step_count_is_reported_not_assumed(self):
        """The count is read from the file, never quoted; this asserts it is non-trivial."""
        self.assertGreaterEqual(len(steps()), 32,
                                "the workflow lost steps; re-read .github/workflows/backend-ci.yml")


class InventoryTests(unittest.TestCase):
    def test_every_real_module_is_run_or_explicitly_excluded(self):
        ran = {name for name, _t in steps()}
        uncovered = []
        for name, path in test_modules().items():
            if name in ran or name in EXCLUDED:
                continue
            uncovered.append("%s (%d tests)" % (path.relative_to(REPO_ROOT),
                                               len(re.findall(r"def test_",
                                                              path.read_text(encoding="utf-8")))))
        self.assertFalse(
            uncovered,
            "real test modules that never run in CI and carry no exclusion reason:\n"
            + "\n".join(uncovered))

    def test_every_excluded_entry_still_exists(self):
        real = set(test_modules())
        stale = sorted(name for name in EXCLUDED if name not in real)
        self.assertFalse(stale, "EXCLUDED names modules that are gone: %s" % stale)

    def test_exclusions_and_steps_do_not_overlap(self):
        ran = {name for name, _t in steps()}
        both = sorted(ran & set(EXCLUDED))
        self.assertFalse(both, "a suite is both run and excluded: %s" % both)


class TheNewlyWiredSuitesTests(unittest.TestCase):
    """The three suites this lane wired up were offline; pin that they stay wired."""

    WIRED = ("test_host_resolvers.py", "test_stream_resolvers.py", "test_convert_mp4moviez.py")

    def test_the_previously_unwired_offline_suites_are_steps(self):
        ran = {name for name, _t in steps()}
        absent = [name for name in self.WIRED if name not in ran]
        self.assertFalse(absent, "regressed to unwired: %s" % absent)

    def test_they_are_not_in_the_exclusion_table(self):
        for name in self.WIRED:
            self.assertNotIn(name, EXCLUDED)


if __name__ == "__main__":
    print("fixture: %s (offline — reads the workflow and two directory listings)"
          % pathlib.Path(__file__).name)
    unittest.main(verbosity=2)
